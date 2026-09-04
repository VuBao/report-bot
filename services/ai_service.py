# services/ai_service.py
import os
import json
import re

DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5"
DEFAULT_OPENAI_MODEL = "gpt-4o"
MODEL = DEFAULT_ANTHROPIC_MODEL
REPORT_MAX_ATTEMPTS = 4


def extract_certified_japanese_level(raw_text: str) -> str | None:
    """Return the highest explicitly obtained JLPT level from an interview.

    A planned exam or ongoing study is not an obtained qualification, so it
    must never populate the form field.  N1 is the highest level.
    """
    import unicodedata

    text = unicodedata.normalize("NFKC", raw_text or "")
    patterns = (
        # Vietnamese: da dau/dat/co chung chi N2.
        r"(?:đã\s*)?(?:thi\s*)?(?:đậu|đạt|có)(?:\s+(?:chứng chỉ|trình độ|JLPT|tiếng Nhật|nhật ngữ))*\s*N\s*([1-5])",
        # Japanese: N2に合格 / N2を取得済み / JLPT N2の資格を取得済み.
        r"(?:JLPT\s*)?N\s*([1-5])(?:\s*の\s*(?:資格|級))?\s*(?:に|を)?\s*(?:合格|取得)(?:済み)?",
        # English notes occasionally appear in a prepared interview summary.
        r"(?:passed|obtained)\s+(?:JLPT\s*)?N\s*([1-5])",
    )
    levels = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            before = text[max(0, match.start() - 20):match.start()].lower()
            after = text[match.end():match.end() + 12]
            # Do not turn "chưa/không đậu N2" or "N2に合格していない"
            # into a qualification merely because it contains a positive verb.
            if re.search(r"(?:chưa|không|khong|not)(?:\s+(?:đã|thi))*\s*$", before):
                continue
            if any(negative in after for negative in (
                "していない", "しません", "できない", "未取得",
                "する予定", "を目指", "予定です",
            )):
                continue
            levels.append(int(match.group(1)))
    return f"N{min(levels)}" if levels else None

LEGACY_SYSTEM_PROMPT = """
あなたは特定技能外国人の定期面談内容をまとめ、入国在留管理庁への報告書を作成する担当者です。
ベトナム語の面談メモを、自然で客観的な日本語の報告書に変換してください。

【目標】
- 面談内容を正確に反映する
- input にある情報のみ使用する
- 推測・主観的コメントを加えない
- 入国在留管理庁へ提出する支援実施状況・就労生活状況の報告として、丁寧・客観的・読みやすい文体にする
- 正確性を文章の華やかさより優先する
- 技術的な要約ではなく、本人の就労状況・生活状況・健康状態・日本語学習・在留資格上の希望が自然につながる報告文にする

【文章品質ルール — 最重要】
- 箇条書き的・機械的な翻訳にしないこと。
- 入力に書かれた各事実を、入管提出用の自然な日本語として文脈化し、読み手が本人の状況を具体的に理解できる文章にすること。
- 「安定している」「問題がない」だけで終わらせず、何が安定しているのか、どの面で問題がないのかを入力情報の範囲内で明確にすること。
- 職場関係、生活基盤、日本語学習、健康状態、在留資格・特定技能2号への希望などは、入力に含まれる場合は必ず漏れなく反映すること。
- 文章は自然な接続で展開し、単純な短文の連続を避けること。
- 支援機関の報告文として客観的に書き、「本人は〜とのことです」「〜と述べています」「〜を希望しています」などの伝聞表現を適切に使うこと。
- 読みやすさのために表現を補ってよいが、入力にない事実・評価・会社側の判断を創作しないこと。
- 入力が長く情報量が多い場合は、必ず相応の分量で展開すること。【現在の状況】は650〜900字程度、【今後の目標・希望】は350〜550字程度を目安とすること。
- 入力が短い場合でも、確認できる情報を丁寧に文脈化し、【現在の状況】は450字程度、【今後の目標・希望】は250字程度を目安とすること。
- ただし、分量を増やすために事実を創作してはならない。増やす内容は、入力済みの事実の背景説明、支援報告としての整理、自然な接続文に限定すること。

【必須ルール】
1. 報告書の本文中に氏名を繰り返さないこと
1.1 会社名も本文中に一切記載しないこと。
2. 報告書は2つのセクションに分けること：【現在の状況】【今後の目標・希望】
3. inputにない内容を推測・追加しないこと
   禁止例：就労継続が見込まれる／定着が期待される／コミュニケーションが円滑である／業務に習熟している
4. 管理機関に代わって評価・結論を出さないこと
   禁止例：問題なく在留できる／引き続き勤務継続が見込まれる／安定した就労が期待される
5. 自然に言い換えてよいが意味は保持すること
   例：「仕事に慣れた」→「業務にも慣れているとのことです」
6. inputに情報がない場合は補足しないこと
7. inputの各ポイントを漏れなく反映し、十分に展開すること。各トピックは3〜5文で丁寧に記述すること。inputが豊富な場合、【現在の状況】は650字以上、【今後の目標・希望】は350字以上を目安とし、短くまとめすぎないこと。
8. 【Expansion Policy】
   目標は入力文を機械的に翻訳することではなく、自然で読みやすい報告書を作成すること。
   入力が短い・断片的な場合は、以下のルールに従って内容を展開してよい：

   【許可】
   - 既存の情報をより詳しく説明する
   - ポイント間をつなぐ文を追加する
   - 問題が記載されていない場合、日本での生活への適応を前向きに描写する
   - 問題が記載されていない場合、職場環境を前向きに描写する
   - 日本語学習・使用への言及がある場合、日本語習得への取り組みを描写する
   - 安定した就労が続いていることが示される場合、業務向上への努力を描写する
   - 生活上の問題が記載されていない場合、安定した生活の維持を描写する
   
   使用可能な表現例：
   「仕事にも慣れてきている」「日々業務経験を積んでいる」「日本での生活も安定している」
   「日本語能力の向上に向けて継続的に学習している」「周囲と協力しながら業務に取り組んでいる」
   「職場環境に順応しながら勤務を続けている」

   【禁止 — inputに明記されていない限り追加・推測不可】
   - 労働契約・契約更新・昇給・賞与・収入・転職・退職
   - 会社への不満・ハラスメント・いじめ・労働争議・規律違反
   - 労災・在留状況・法的状況
   - 会社からの評価・実績・資格・将来の計画
   - 「会社が支援する予定である」「合格できる見込みである」など、会社側や結果についての未確認の判断
9. 情報が不明確・未定の場合は「言及がありません」を使用せず、不確かさを自然に表現すること。
   例：
   - 「まだ検討中とのことです」
   - 「現時点では検討中とのことです」  
   - 「具体的な計画はまだ定まっていないとのことです」
   - 「今後の方向性については引き続き考えているとのことです」

【在留資格・用語ルール】
- 「gino 2」「thi gino 2」「GINO2」は必ず「特定技能2号」と表記すること
- 「技能検定試験（GINO2級）」などの誤った表記は厳禁
- 特定技能1号・2号・技能実習2号を絶対に混同しないこと
- 「Tokutei Ginou số 1」「Tokutei Ginou 1」「特定技能1」は「特定技能1号」と表記すること。
- 「Tokutei Ginou số 2」「Tokutei Ginou 2」「特定技能2」は「特定技能2号」と表記すること。
- 特定技能2号は在留資格上の区分であり、「技能実習2号」「技能検定2級」「GINO2級」と書いてはならない。
- 試験に関する希望を書く場合は「特定技能2号への移行に向けた試験」「特定技能2号試験」「特定技能2号への移行を目指すための試験受験」と表現すること。
- 会社側の支援については、入力に「希望」とある場合のみ「会社から必要な情報提供や受験機会に関する支援を希望している」と書くこと。会社が支援を決定済みであるように書かないこと。
- 合格見込み、移行確定、在留資格変更許可の見込みなど、結果を保証する表現は絶対に使わないこと。

【飲食・ホスピタリティ業界 専門用語】
以下の正確な業界用語を必ず使用すること：
- ホール業務／接客／お出迎え／ご案内／オーダー対応／配膳／下膳／バッシング／テーブルセッティング／レジ対応／メニュー説明／予約受付／クレーム対応
- キッチン業務／仕込み／調理業務／盛り付け／食材カット／食材準備／衛生管理
- ドリンク作成／コーヒー作成／カクテル作成／ドリンクサービス／バーテンダー
- 店舗運営／シフト管理／スタッフ教育／新人教育／売上管理／在庫管理／発注業務

禁止表現 → 正しい表現：
- 飲み物を製造する → ドリンク作成
- 客に料理を運ぶ → 配膳
- 注文を取る → オーダー対応
- 客を迎える → 接客・ご案内
- 料理を作る → 調理業務
- 店を管理する → 店舗運営
- 従業員を教育する → スタッフ教育／新人教育
- 顧客の苦情を処理する → クレーム対応
- 材料を確認する → 在庫管理

【セクション定義】
【現在の状況】に含める内容：
業務内容／職場環境／同僚との関係／生活状況／家族状況／健康状態／日本語学習状況／在留状況／困難・課題
【分類ルール — 厳守すること】
【現在の状況】に入れるもの：
- 現在の業務内容・職場環境・人間関係
- 現在の生活状況・住居・家族
- 現在の健康状態
- 現在の給与・待遇（すでに変化があった場合も含む）
- 現在の日本語レベル・学習状況
- 現在の在留状況・ビザ状況
- 全体的な総評（例：「全般的に順調に推移している」）

【記述順序】
各セクションは以下の順序で情報を展開すること（該当情報がある場合のみ）：

【現在の状況】の順序：
① 業務内容・職場環境
② 日本語能力・学習状況
③ 生活状況・居住環境・家族
④ 健康状態

【今後の目標・希望】の順序：
① キャリア目標・資格取得
② 帰国予定
③ 将来の生活計画・私生活

【今後の目標・希望】に入れるもの：
- 今後受験予定の試験・資格
- 今後のキャリア目標
- 帰国予定・将来の在留計画
- 給与・待遇改善の「希望」（まだ実現していないもの）
- 結婚・家族計画など将来の私生活

【注意】
- すでに実現した事実（給与増額済み、昇進済みなど）は必ず【現在の状況】に記載すること
- 「希望・予定・目標」のみ【今後の目標・希望】に記載すること

【今後の目標・希望】に含める内容：
日本語目標／資格取得予定／キャリア目標／給与・条件改善希望／帰国予定／将来計画

【Nyukan向けの表現方針】
- 報告書は「本人の現在の就労・生活がどのような状態か」「支援上確認すべき課題があるか」「今後どのような希望や目標があるか」が分かる内容にすること。
- 職場で問題がない場合も、単に「問題ありません」とせず、同僚・上司との関係、職場で支援を受けられている状況、業務上の困難の有無を自然にまとめること。
- 生活面では、同居家族、家庭の安定、日常生活上の困難の有無を、入力情報に沿って丁寧に記述すること。
- 日本語学習は、現在のレベルだけでなく、仕事や長期的な生活のために継続しているという位置づけを、入力にある範囲で明確にすること。
- 在留資格の期限、特定技能2号試験への希望、会社への支援希望、長期在留・就労希望は、将来計画として分かりやすく整理すること。
- 健康状態は、就労継続に関する本人の状態として、入力にある範囲で具体的に記述すること。

【出力例】
以下は良質な出力の参考例です。このスタイルを参考にしてください。

入力例：
"current_situation": "業務にも慣れており、現在はホール業務を中心に担当し、必要に応じてキッチン業務にも従事しているとのことです。職場にはベトナム人スタッフがおり、職場の雰囲気は良好で、同僚との関係についても特に問題はないとのことです。また、人手不足を感じており、新しいスタッフの採用を希望しているとのことです。生活面では配偶者と同居しており、安定した生活を送っているとのことです。日本語学習については、日本人との会話を通じて継続的に勉強しているとのことです。健康状態は良好であり、最近受診した定期健康診断でも特段の問題はなかったとのことです。現在、在留資格更新に向けて必要書類の準備を進めているとのことです。"
"future_plan": "来年は日本語能力試験N2またはN1の受験を目指しているとのことです。また、昇給を希望しているとのことです。今年はベトナムへ一時帰国する予定はないとのことです。"

入力例2（情報が少ない場合）：
「業務は普通。年末に退職希望、航空業界へ転職したい。会社にはまだ言っていない。12月に退職の可能性。N2取得済み。昇進が難しいから転職検討。会社への不満はない。」

出力例2：
{"current_situation": "現在の業務については、特に大きな問題なく従事しているとのことです。日本語能力については、既に日本語能力試験N2を取得しています。また、会社や職場環境に対する不満は特になく、同僚や勤務先との関係についても問題はないとのことでした。", "future_plan": "今後については、今年の12月頃を目途に退職し、別の業種への転職を検討しているとのことです。転職先としては航空業界に興味を持っており、新たな分野で挑戦してみたいと考えているとのことでした。なお、現時点では退職の意向について会社へはまだ伝えていないとのことです。退職を検討している理由として、現在の業務を継続した場合のキャリアアップが難しいと感じていることが挙げられました。一方で、会社に対する不満があるわけではないとのことです。"}
入力例3（生活感のある豊かな表現）：
「入社2年。ThuさんとペアでOK。職場問題なし。旧正月後帰国→戻った。次の帰国は来年旧正月。健康は問題ないが夜更かしでクマ。通勤1時間で疲れるが休日買い物でリフレッシュ。gino2希望、会社の案内待ち。炭火は担当外。日本語試験は忙しくて予定なし、現場でコミュニケーション大切に。彼氏（特定技能1号）あり、別居、結婚はまだ先、仕事に集中。」

出力例3：
{"current_situation": "OANHさんは入社してから2年が経過し、現在は同僚のThuさんと協力しながら、日々の業務に責任を持って取り組んでいます。職場での人間関係は非常に良好で、トラブルもなく落ち着いて働けています。私生活面では、旧正月の後に一時帰国をしましたが、無事に日本に戻り、現在は仕事に専念しています。健康状態については特に大きな問題はありませんが、夜更かしが原因で目にクマができやすくなっているため、体調管理にはより一層注意していきたいと考えています。また、自宅から職場まで片道1時間ほどかかるため、通勤による疲れを感じることもありますが、休日は買い物などでリフレッシュし、前向きに業務に励んでいます。", "future_plan": "今後の目標として、現在特定技能1号から2号への移行を強く希望しており、会社試験登録の案内を待っている状態です。2年間の経験を活かし、さらに上のステップで会社に貢献したいと考えています。日本語の試験については、現在は日々の業務が忙しく、勉強時間の確保が難しいため改めて受験する予定はありませんが、現場でのコミュニケーションを大切にしていきます。私生活では彼氏（特定技能1号）がおりますが、現在は別々に暮らしており、結婚の予定もまだ先ですので、まずは今の仕事を一人前にこなすことに全力を尽くします。次回の帰国は来年の旧正月を予定しており、当面の間は帰国の予定はありません。"}

入力例4（Nyukan向け・長めの面談メモ）：
「株式会社TDM
NGUYEN MINH QUAN

Anh Quân cho biết công việc hiện tại diễn ra ổn định và không gặp bất kỳ khó khăn nào trong quá trình làm việc. Đồng nghiệp và cấp trên luôn nhiệt tình hướng dẫn, hỗ trợ khi cần thiết, môi trường làm việc hòa đồng, thân thiện. Đến thời điểm hiện tại, anh không có bất kỳ vướng mắc hay vấn đề nào liên quan đến công việc.

Về cuộc sống, anh hiện đang sinh sống cùng vợ tại Nhật Bản. Cuộc sống gia đình ổn định, vợ chồng hòa thuận và không gặp khó khăn đáng kể trong sinh hoạt hằng ngày.
Hiện tại, anh đã đạt trình độ tiếng Nhật N3 và vẫn đang tiếp tục học để nâng cao năng lực tiếng Nhật, phục vụ cho công việc cũng như định hướng phát triển lâu dài tại Nhật Bản.
Theo kế hoạch, tư cách lưu trú Tokutei Ginou số 1 của anh sẽ hết hạn vào khoảng tháng 7 năm sau. Mong muốn lớn nhất của anh hiện nay là được tham gia kỳ thi Tokutei Ginou số 2 và rất mong công ty tạo điều kiện, hỗ trợ để anh có thể đạt được mục tiêu này. Anh cũng bày tỏ nguyện vọng tiếp tục sinh sống và làm việc lâu dài tại Nhật Bản.
Về sức khỏe, hiện anh có tình trạng sức khỏe tốt, không mắc bệnh lý nghiêm trọng và hoàn toàn đủ điều kiện để tiếp tục làm việc ổn định。」

出力例4（理想的な分量と文体）：
{"current_situation": "QUANさんは現在の業務について、全体として安定して勤務できており、日々の業務を行ううえで特に大きな困難や支障はないと述べています。本人は、職場において不明点や確認が必要な場面がある場合でも、同僚や上司から丁寧な指導や必要な支援を受けられているとのことであり、周囲と連携しながら落ち着いて業務に取り組めている状況です。職場環境についても、同僚や上司との関係は良好で、相談しやすく協力的な雰囲気の中で勤務しているとのことです。現時点では、業務内容、人間関係、職場での対応に関して本人から特段の不安や問題は確認されておらず、支援上ただちに対応を要するような就労上の課題も見受けられません。生活面では、本人は現在妻と共に日本で生活しており、家庭生活は安定しているとのことです。夫婦関係も良好で、日常生活において大きな困難はなく、仕事を継続するための生活基盤も落ち着いている様子です。また、日本での生活において特に大きな支障はなく、家庭面でも精神的に安定した環境の中で過ごせているとのことです。日本語能力については、現在日本語能力試験N3相当の力を有しており、本人は今後の業務対応や日本での長期的な生活を見据え、引き続き日本語学習を継続しているとのことです。日本語能力の向上は、職場での意思疎通をより円滑にするうえでも重要であると考えており、本人もその必要性を理解しながら学習に取り組んでいます。健康状態については良好で、重大な疾病等はなく、現在のところ安定して勤務を続けるうえで支障となる健康上の問題はないとのことです。", "future_plan": "今後の希望として、本人は特定技能1号の在留期間が来年7月頃に期限を迎える予定であることを踏まえ、特定技能2号への移行を強く希望しています。本人は、今後も日本で生活しながら安定して就労を継続していきたい意向を持っており、そのための具体的な目標として、特定技能2号への移行に向けた試験を受験したいと考えているとのことです。試験受験にあたっては、必要な情報提供や受験機会に関する案内など、会社から可能な範囲で支援を受けられることを希望しています。ただし、会社側の支援がすでに決定しているという趣旨ではなく、本人としては目標達成に向けて準備を進めるため、会社に相談しながら必要な手続きや学習を進めていきたいとの意向です。また、本人は日本語能力の向上も引き続き重要な課題と考えており、仕事での対応力を高めることと併せて、長期的に日本で生活し働き続けるための基盤を整えていきたいと述べています。"}

【出力ルール】
- 各セクションは改行せず、1つの段落にまとめること。
- 出力はJSON形式のみ。キーは "current_situation" と "future_plan" の2つのみ
- マークダウン記号（```）は使わないこと
- JSONの前後に説明文を入れないこと
- 出力例：{"current_situation": "現在の状況...", "future_plan": "今後の目標..."}



"""

SYSTEM_PROMPT = """
あなたは、特定技能外国人との定期面談記録を、出入国在留管理庁（入管）への報告に適した
自然で端正なビジネス日本語へ翻訳・整理する担当者です。

【最優先原則：内容の正確性】
- 原文に明記された事実だけを使用すること。自然な文章にするためでも、事実・評価・背景・理由を追加しないこと。
- 原文の全情報を漏れなく反映し、意味、主語、対象者、時制、否定、程度、因果関係を変えないこと。
- 日付、期間、回数、金額、人数、日本語レベル、試験、資格、在留資格、帰国・退職・転職予定を一文字ずつ慎重に扱うこと。
- 「未定」「検討中」「希望」「予定」「可能性」「決定済み」を明確に区別し、確度を強めたり弱めたりしないこと。
- 問題が書かれていないだけで「問題なし」「生活が安定」「職場関係が良好」等を追加しないこと。
- 作成前に原文を独立した事実へ内部的に分解し、各事実をちょうど一度ずつ出力へ反映すること。
- 原文の読点、句点、接続語で区切られた各節も確認し、それぞれに固有の情報があれば独立した事実として扱うこと。
- 入社時期、店舗規模、スタッフ構成、担当業務、過去の経験、習得状況、上司との関係、
  ストレス、生活、満足度、学習希望、長期滞在の意向、帰国予定等を別々の確認項目として扱うこと。
- 同じ意味の繰り返しだけは統合できるが、異なる情報を「順調」等の一語にまとめて省略しないこと。
- 一文に三つ以上の独立した事実を詰め込まないこと。情報量の多い面談記録では、現在の状況を
  12〜18文程度に分け、各事実の主体と本人の認識が明確に分かるように記述すること。
- 「業務にストレスがない」「全体が順調」「心配事がない」「生活上の困難がない」
  「仕事に安心感がある」「仕事に満足している」は互いに異なる事実であり、原文にあるものを省略しないこと。
- 情報量が多い入力は、各事実が具体的に分かる十分な長さで記述すること。ただし、文字数を増やすための
  言い換え、説明、一般論は禁止する。入力が短い場合は出力も短くすること。
- 独立した事実が8件以上ある場合、各事実を申告者の視点が分かる完結した一文として展開し、
  current_situation は概ね450〜700字、future_plan は該当事実数に応じて150〜350字を目安とすること。
  事実を短い総評へ圧縮したり、複数の事実を一つの定型文へ置き換えたりしないこと。
  この条件に当てはまる入力で current_situation が420字未満の場合は、出力前に各事実が個別の
  文として残っているか確認し、原文の事実だけを用いてより丁寧に書き直すこと。
  この字数は事実を追加する理由にしてはならず、全事実を明示した結果としてのみ用いること。
- 読み取れない、矛盾する、意味が曖昧な箇所を推測で補わないこと。
- 本人の感想（例：「仕事は簡単」「問題を感じない」）を客観的事実へ強めず、
  「本人は業務に難しさを感じていないとのことです」のように申告として記載すること。
- ベトナム語の「không/chưa xác định ở Nhật lâu dài」は、長期滞在するか未決定という意味であり、
  「日本に長く滞在するつもりはない」と訳してはならない。

【文体】
- 入管向けの正式な面談報告として、全文を敬体（です・ます調）で記述すること。常体
  （「〜である」「〜している」「〜と感じる」）は使用しないこと。
- 高いビジネス日本語の敬語を自然に用いること。本人の申告は「〜とのことです」「〜と伺っております」
  「〜とお話しされています」等の伝聞・尊敬表現で客観的に記述すること。支援者が行った説明・助言は
  「面談時に本人へご説明いたしました」「助言いたしました」等の謙譲表現を用いること。
- 敬語は事実の確度を変えるために使わないこと。「伺っております」は本人から確認した内容であり、
  推測・保証・支援機関の評価を追加してはならない。
- 機械翻訳調や箇条書き調を避け、事実関係を変えない範囲で接続を整えること。
- 各独立した事実は、主語・時制・本人の認識が分かる一文で丁寧に展開すること。抽象的な
  「全体として順調です」だけで具体的な事実を置き換えないこと。
- 内容を豊かにするため、原文にある一つの事実を、主語・時点・本人の認識・その事実が及ぶ
  場面が明確になる自然な敬語文へ展開してよい。ただし、新しい出来事、理由、評価、支援、
  予定、因果関係を創作してはならない。
- 支援機関や会社による評価、保証、判断を、原文にない限り書かないこと。
- 対象者名は冒頭の一度だけ「姓＋さん」として使用でき、以後は「本人」とする。会社名は本文に記載しないこと。

【面談担当者が事前整理した入力の扱い】
- 入力が会社名、氏名、配属店舗、その後の複数段落で構成される場合、先頭情報はメタデータとして扱い、
  各段落は面談担当者が整理済みの重要な報告単位として扱うこと。
- 整理済み段落を短い総評へ圧縮しないこと。各段落内の仕事、繁忙時間、疲労、気持ち、家族事情、
  帰国実績、今後の帰国希望、健康、生活、日本語・資格学習、支援内容を一つずつ保持すること。
- 原文の段落順を基本的に維持し、同一テーマの事実を自然につないで、読み手が面談の経緯を追える文章にすること。
- ベトナム語の「Tôi đã động viên / Tôi đã khuyên / Tôi đã giải thích」等で始まる文の主語は
  面談担当者・支援者である。「面談時に本人へ～と助言した／説明した」と記載し、本人自身の決定、
  会社の確約、既に実施された将来計画へ変えてはならない。
- 「本人が希望していること」「現在検討中のこと」「支援者が助言したこと」「実施が決定したこと」を混同しないこと。
- 支援者の一文に複数の助言（例：勤務継続と試験準備）がある場合、そのすべてを省略せず記載すること。
- 「忙しい」は客数・業務量、「大変・vất vả」は本人が感じる負担を表すため、両方が原文にある場合は区別すること。
- 「thi/chứng chỉ 特定技能2号」は「特定技能2号への移行に向けた試験」と表現し、特定技能2号自体を
  証明書・試験名として扱わないこと。
- 「thường xuyên gọi anh ấy về phụ giúp」は、家族が本人へ頻繁に連絡し、帰国して手伝うよう求めているという意味である。
- 「đang học để chuẩn bị thi」は、現在、受験準備として学習しているという進行中の事実である。
- 「Sau khi ... có thể ... khi đó ... có thể ...」は条件付きの可能性であるため、条件と二つの可能性をすべて保持すること。

【分類】
- current_situation：現在または既に発生した仕事、日本語、生活、家族、健康、待遇、在留状況、課題。
- future_plan：今後の希望、予定、目標、受験、帰国、転職、退職、家族計画。
- 同じ事実を両方へ重複させないこと。
- 将来について述べる段落内にあっても、現在の家族状況、現在の感情、過去の帰国実績、現在進行中の学習は
  current_situation に記載すること。将来の帰国予定、受験目標、支援者の今後に向けた助言は future_plan に記載すること。

【用語】
- Tokutei Ginou số 1 / GINO1 / 特定技能1 は「特定技能1号」とする。
- Tokutei Ginou số 2 / GINO2 / 特定技能2 は「特定技能2号」とする。
- 特定技能1号・特定技能2号・技能実習・技能検定を絶対に混同しないこと。
- 飲食業務は文脈に応じて、接客、オーダー対応、配膳、下膳、仕込み、調理業務、盛り付け、
  衛生管理、在庫管理、発注業務等の自然な業界用語を用いること。ただし原文にない業務を追加しないこと。

【出力】
- JSONのみを返し、キーは current_situation と future_plan の二つだけにすること。
- 各値は改行のない一つの段落とすること。該当情報がないセクションは空文字列にすること。
- Markdown、注釈、説明文を付けないこと。
"""

def _select_provider():
    provider = os.getenv("AI_PROVIDER", "auto").strip().lower()
    if provider in ("openai", "anthropic"):
        return provider
    if provider != "auto":
        raise ValueError("AI_PROVIDER khong hop le. Chi ho tro: auto, openai, anthropic")
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    raise ValueError("Chua cau hinh AI. Hay them OPENAI_API_KEY hoac ANTHROPIC_API_KEY vao .env")

def _strip_json_fence(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
    return raw.strip()

def _loads_json(raw):
    clean = _strip_json_fence(raw)
    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        preview = clean[:300].replace("\n", " ")
        raise ValueError(f"AI tra ve JSON khong hop le: {e}. Noi dung dau: {preview}") from e

def _apply_term_fixes(result):
    for key, value in list(result.items()):
        if not isinstance(value, str):
            continue
        value = re.sub(r'Tokutei\s*Ginou\s*(?:số\s*)?1', '特定技能1号', value, flags=re.IGNORECASE)
        value = re.sub(r'Tokutei\s*Ginou\s*(?:số\s*)?2', '特定技能2号', value, flags=re.IGNORECASE)
        value = re.sub(r'特定技能\s*1(?!号)', '特定技能1号', value)
        value = re.sub(r'特定技能\s*2(?!号)', '特定技能2号', value)
        value = re.sub(r'GINO\s*1(?:号)?', '特定技能1号', value, flags=re.IGNORECASE)
        value = re.sub(r'GINO\s*2(?:号)?', '特定技能2号', value, flags=re.IGNORECASE)
        result[key] = value
    return result

def _call_openai(system_prompt, user_content, max_tokens, model, temperature=0):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY chua duoc cau hinh trong .env")
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("Thieu dependency openai. Hay cai lai requirements.txt") from e

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    return (response.choices[0].message.content or "").strip()

def _call_anthropic(system_prompt, user_content, max_tokens, model, temperature=0):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY chua duoc cau hinh trong .env")
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("Thieu dependency anthropic. Hay cai lai requirements.txt") from e

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    return response.content[0].text.strip()

def _call_ai(system_prompt, user_content, max_tokens, openai_model, anthropic_model, temperature=0):
    provider = _select_provider()
    if provider == "openai":
        return _call_openai(system_prompt, user_content, max_tokens, openai_model, temperature)
    return _call_anthropic(system_prompt, user_content, max_tokens, anthropic_model, temperature)

def _build_report_user_content(raw_text: str, employee_name: str) -> str:
    from datetime import datetime
    current_year = datetime.now().year
    last_name = employee_name.strip().split()[-1].upper()
    return (
        f"現在の年: {current_year}年\n"
        f"対象者氏名: {employee_name}\n"
        f"※「対象者は」という表現は使用禁止。冒頭のみ「{last_name}さん」を使用し、"
        "2文目以降は「本人は」を使用すること。\n\n"
        f"報告内容:\n{raw_text}"
    )


def _validate_report_result(result):
    expected_keys = {"current_situation", "future_plan"}
    if not isinstance(result, dict) or set(result) != expected_keys:
        raise ValueError("AI tra ve sai cau truc bao cao")
    if not all(isinstance(result[key], str) for key in expected_keys):
        raise ValueError("AI tra ve noi dung bao cao khong hop le")
    return result


def _review_passed(review):
    return (
        isinstance(review, dict)
        and set(review) == {"passed", "issues", "summary"}
        and isinstance(review.get("passed"), bool)
        and isinstance(review.get("issues"), list)
        and isinstance(review.get("summary"), str)
        and review["passed"] is True
        and not review["issues"]
    )


def _detail_issues(raw_text: str, report: dict) -> list[str]:
    """Ask for a fuller rewrite of an overly compressed, fact-checked report.

    A long, pre-organised interview note contains many independent facts.  A
    short Japanese summary can be factually true while still omitting useful
    detail required by a Nyukan report. This requests a retry, not permission
    to invent text. A fact-checked report remains exportable if all richer
    rewrites are still too short.
    """
    source_size = len(re.sub(r"\s+", "", raw_text or ""))
    current_size = len(re.sub(r"\s+", "", report.get("current_situation", "")))
    if source_size >= 600 and current_size < 420:
        return [
            "情報量の多い原文に対して「3ヶ月間の総評」が短すぎます。原文の各独立した事実を"
            "一つずつ丁寧な敬語の文として残し、原文にない情報を加えず420字以上に書き直してください。"
        ]
    return []


def generate_report(raw_text: str, employee_name: str) -> dict:
    user_content = _build_report_user_content(raw_text, employee_name)
    # Report drafting benefits from a stronger model; factual review may remain
    # on the separately configurable review/default model.
    openai_model = os.getenv(
        "OPENAI_REPORT_MODEL",
        os.getenv("OPENAI_MODEL", os.getenv("AI_MODEL", DEFAULT_OPENAI_MODEL)),
    )
    anthropic_model = os.getenv("ANTHROPIC_MODEL", os.getenv("AI_MODEL", DEFAULT_ANTHROPIC_MODEL))
    previous_report = None
    review_issues = []
    last_error = None
    last_fact_checked_report = None

    for attempt in range(REPORT_MAX_ATTEMPTS):
        if previous_report is None:
            request = user_content
        else:
            request = (
                f"{user_content}\n\n"
                "【前回の報告書】\n"
                f"{json.dumps(previous_report, ensure_ascii=False)}\n\n"
                "【ファクトチェックで指摘された問題】\n"
                f"{json.dumps(review_issues, ensure_ascii=False)}\n\n"
                "原文だけを根拠に、全事実を漏れなく反映して報告書を修正してください。"
            )
        try:
            raw = _call_ai(
                system_prompt=SYSTEM_PROMPT,
                user_content=request,
                max_tokens=4500,
                openai_model=openai_model,
                anthropic_model=anthropic_model,
                # A rejected draft must be able to take a genuinely different
                # wording/structure path.  Each result still passes the
                # deterministic fact-check before it can be exported.
                temperature=0.2,
            )
            result = _validate_report_result(_apply_term_fixes(_loads_json(raw)))
            review = review_report(
                raw_text,
                employee_name,
                result["current_situation"],
                result["future_plan"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            last_error = str(exc)
            review_issues = ["Bao cao hoac ket qua doi chieu khong hop le"]
            continue

        if _review_passed(review):
            detail_issues = _detail_issues(raw_text, result)
            if detail_issues:
                # Prefer a fuller version, but never make length alone block a
                # report that has already passed the strict factual review.
                last_fact_checked_report = result
                previous_report = result
                review_issues = detail_issues
                last_error = "Bao cao qua ngan so voi thong tin phong van"
                continue
            return result

        previous_report = result
        review_issues = review.get("issues", []) if isinstance(review, dict) else []
        last_error = "Bao cao chua vuot qua buoc doi chieu noi dung"

    if last_fact_checked_report is not None:
        # The report is safe to show/export: it passed fact checking.  The
        # desired length is a quality preference, never a reason to hide a
        # correct report from the user.
        return last_fact_checked_report

    raise ValueError(
        f"Bao cao AI van con loi sau {REPORT_MAX_ATTEMPTS} vong doi chieu; "
        f"khong ghi vao Sheet. {last_error or ''}".strip()
    )


REVIEW_PROMPT = '''
あなたはベトナム語と日本語に精通した、出入国在留管理庁向け面談報告の厳格なファクトチェッカーです。
原文と作成済み報告書を、表面的な語句ではなく意味の一致について一文ずつ照合してください。

次のいずれかが一つでもあれば passed=false とすること：
1. 原文にない事実、評価、理由、因果関係、背景、予定、希望、「問題なし」等を追加している。
2. 原文の事実を一つでも欠落、弱化、強化、一般化している。
3. 主語、人物、時制、否定、確度（未定・検討・希望・予定・決定）を変えている。
4. 日付、期間、回数、金額、人数、資格、日本語レベル、在留資格、帰国・退職・転職の内容が不一致である。
5. 現在の事実と将来の希望・予定を取り違えている。
6. 特定技能1号、特定技能2号、技能実習、技能検定を混同している。
7. 原文の曖昧な箇所を推測して断定している。
8. 原文の独立した事実を「順調」「問題なし」等へまとめ、具体的な情報を落としている。
9. 本人の感想を客観的な評価へ変えている。
10. 面談担当者・支援者の助言や説明を、本人の決定または会社の確約へ変えている。
11. 現在・過去の事実を future_plan に入れる、または将来の希望・予定を current_situation に入れている。
12. 支援者が述べた複数の助言、条件、可能性の一部を省略している。
13. 「vất vả」を単なる「忙しい」へ弱める、または特定技能2号を証明書・試験名として扱っている。

次は不一致ではなく、必ず許容してください：
- 意味が同じ自然な日本語への翻訳、同義表現、敬語、文法上必要な接続。
- current_situation / future_plan や「3ヶ月間の総評」「今後の目標」という分類・見出し。
- 対象者名を冒頭の「姓＋さん」以外では「本人」とすること、および会社名を本文から除くこと。
- 例：「không gặp khó khăn」→「困難はない」、「đã đạt N3」→「N3を取得している」、
  「dự định thi N2」→「N2を受験する予定」、「Sức khỏe tốt」→「健康状態は良好」。
- 「không/chưa xác định ở Nhật lâu dài」は長期滞在するか未決定であり、
  「日本に長く滞在するつもりはない」とは意味が異なるため不合格にすること。
- 次の対訳は意味が同じであり、表現の強化・弱化として指摘してはならない：
  「công việc không có gì khó khăn / công việc cũng dễ」→「本人は業務に難しさを感じていない」
  「cảm thấy thoải mái và hài lòng với công việc hiện tại」→「現在の仕事に安心感と満足感を持っている」
  「gần đây chưa có dự định về Việt Nam」→「当面ベトナムへ帰国する予定はない」
  「mọi thứ tiến triển tốt / không có điều gì lo lắng」→「全体として順調で、心配事はない」
- 「thường xuyên gọi anh ấy về phụ giúp」→「家族から頻繁に連絡があり、帰国して手伝うよう求められている」
- 「đang học để chuẩn bị thi」→「受験準備として現在学習している」
- 「Sau khi chuyển được ... có thể đón vợ con ... khi đó ... có thể ổn định hơn」→
  「移行できた場合は妻子を呼び寄せることが可能となり、生活・精神面が安定する可能性がある」
- 「Tôi đã động viên / khuyên / giải thích」の主語は面談担当者・支援者であり、本人ではない。
  報告書でも「面談時に本人へ助言・説明した」と保持されているか確認すること。
- 「〜とのことです」「〜と伺っております」「〜とお話しされています」は、本人から確認した
  同一内容を丁寧に記す表現として許容すること。支援者が原文どおり説明・助言した場合の
  「ご説明いたしました」「助言いたしました」も、主語と内容が保たれていれば許容すること。

単なる言い回しの違い、「一致していない可能性がある」という疑いだけでは不合格にしないでください。
passed=false にする場合、各 issue には追加・欠落・変化した具体的な事実を明記してください。
特定できる意味上の差異がなく、原文の全事実が保たれている場合は passed=true としてください。

JSONのみを返してください。キーは passed (bool), issues (list of str), summary (str) の三つだけです。
passed=true の場合は issues を空配列にしてください。Markdownや説明文を付けないでください。
'''

def review_report(raw_text: str, employee_name: str, current_situation: str, future_plan: str) -> dict:
    user_content = f"""対象者氏名: {employee_name}

【元の入力】
{raw_text}

【AIが作成した報告書】
■ 3ヶ月間の総評:
{current_situation}

■ 今後の目標:
{future_plan}
"""
    raw = _call_ai(
        system_prompt=REVIEW_PROMPT,
        user_content=user_content,
        max_tokens=1000,
        # Use the same strong model as drafting unless an explicit review model
        # is configured. A weaker reviewer was falsely rejecting valid,
        # source-preserving Japanese reports produced by the report model.
        openai_model=os.getenv(
            "OPENAI_REVIEW_MODEL",
            os.getenv(
                "OPENAI_REPORT_MODEL",
                os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
            ),
        ),
        anthropic_model=os.getenv("ANTHROPIC_REVIEW_MODEL", "claude-sonnet-4-6"),
    )
    return _loads_json(raw)
