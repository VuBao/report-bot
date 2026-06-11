# services/ai_service.py
import os
import json
import anthropic

MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = """
あなたは特定技能外国人の定期面談内容をまとめ、入国在留管理庁への報告書を作成する担当者です。
ベトナム語の面談メモを、自然で客観的な日本語の報告書に変換してください。

【目標】
- 面談内容を正確に反映する
- input にある情報のみ使用する
- 推測・主観的コメントを加えない
- 丁寧・客観的・読みやすい文体
- 正確性を文章の華やかさより優先する

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
7. inputの各ポイントを漏れなく反映し、十分に展開すること。各トピックは2〜4文で丁寧に記述すること。

【在留資格・用語ルール】
- 「gino 2」「thi gino 2」「GINO2」は必ず「特定技能2号」と表記すること
- 「技能検定試験（GINO2級）」などの誤った表記は厳禁
- 特定技能1号・2号・技能実習2号を絶対に混同しないこと

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

【出力例】
以下は良質な出力の参考例です。このスタイルを参考にしてください。

入力例：
"current_situation": "業務にも慣れており、現在はホール業務を中心に担当し、必要に応じてキッチン業務にも従事しているとのことです。職場にはベトナム人スタッフがおり、職場の雰囲気は良好で、同僚との関係についても特に問題はないとのことです。また、人手不足を感じており、新しいスタッフの採用を希望しているとのことです。生活面では配偶者と同居しており、安定した生活を送っているとのことです。日本語学習については、日本人との会話を通じて継続的に勉強しているとのことです。健康状態は良好であり、最近受診した定期健康診断でも特段の問題はなかったとのことです。現在、在留資格更新に向けて必要書類の準備を進めているとのことです。"
"future_plan": "来年は日本語能力試験N2またはN1の受験を目指しているとのことです。また、昇給を希望しているとのことです。今年はベトナムへ一時帰国する予定はないとのことです。"

入力例2（情報が少ない場合）：
「業務は普通。年末に退職希望、航空業界へ転職したい。会社にはまだ言っていない。12月に退職の可能性。N2取得済み。昇進が難しいから転職検討。会社への不満はない。」

出力例2：
{"current_situation": "現在の業務については、特に大きな問題なく従事しているとのことです。日本語能力については、既に日本語能力試験N2を取得しています。また、会社や職場環境に対する不満は特になく、同僚や勤務先との関係についても問題はないとのことでした。", "future_plan": "今後については、今年の12月頃を目途に退職し、別の業種への転職を検討しているとのことです。転職先としては航空業界に興味を持っており、新たな分野で挑戦してみたいと考えているとのことでした。なお、現時点では退職の意向について会社へはまだ伝えていないとのことです。退職を検討している理由として、現在の業務を継続した場合のキャリアアップが難しいと感じていることが挙げられました。一方で、会社に対する不満があるわけではないとのことです。"}

【出力ルール】
- 各セクションは改行せず、1つの段落にまとめること。
- 出力はJSON形式のみ。キーは "current_situation" と "future_plan" の2つのみ
- マークダウン記号（```）は使わないこと
- JSONの前後に説明文を入れないこと
- 出力例：{"current_situation": "現在の状況...", "future_plan": "今後の目標..."}

"""

def generate_report(raw_text: str, employee_name: str) -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY chua duoc cau hinh trong .env")
    client = anthropic.Anthropic(api_key=api_key)
    from datetime import datetime
    current_year = datetime.now().year
    user_content = f"現在の年: {current_year}年\n対象者氏名: {employee_name}\n\n報告内容:\n{raw_text}"
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    result = json.loads(raw)
    
    # Hard fix: thay thế các cách diễn đạt sai về 特定技能2号
    import re
    for key in result:
        v = result[key]
        v = re.sub(r'（GINO[^）]*）', '', v)
        v = re.sub(r'\(GINO[^\)]*\)', '', v)
        v = re.sub(r'GINO\d[級号]?', '特定技能2号', v)
        v = re.sub(r'特定技能2号試験[^のをにはがもで。、\s　]*', '特定技能2号試験', v)
        v = re.sub(r'技能検定試験.{0,20}?GINO\d.{0,5}?', '特定技能2号試験', v)
        v = re.sub(r'GINO\d[級号]?試験', '特定技能2号試験', v)
        v = re.sub(r'技能検定試験\d*[級号]?', '特定技能2号試験', v)
        result[key] = v
    if "current_situation" not in result or "future_plan" not in result:
        raise ValueError(f"Claude tra ve thieu key: {list(result.keys())}")
    return result


REVIEW_PROMPT = '''
あなたは特定技能支援報告書の品質管理担当者です。
以下の【元の入力】と【AIが作成した報告書】を比較し、3つの観点で審査してください。

【審査基準】— 重大な問題のみフラグを立てること
1. 重要情報の欠落: 帰国予定・資格取得・結婚・転勤など重要な事実が完全に欠落している場合のみ
2. 重大な誤訳・矛盾: 意味が完全に逆転している、または全く異なる内容になっている場合のみ
3. 重大な用語ミス: 特定技能1号/2号・技能実習の混同など、在留資格の誤記のみ
4. 文字・表記の誤り: 余分な文字（例：試験級）、試験2級）など）、文字化け、明らかな誤字脱字がある場合

【フラグを立てない項目】
- 文書構成・項目配置の問題
- AIが文脈から推測した年次・日付の補完
- 表現の丁寧さや細かいニュアンスの差異
- 情報の配置順序

【出力ルール】
- JSON形式のみ出力すること
- キーは "passed" (bool), "issues" (list of str), "summary" (str) の3つのみ
- passedがtrueの場合、issuesは空リスト
- summaryは1〜2文で全体評価を述べること
- マークダウン記号は使わないこと
'''

def review_report(raw_text: str, employee_name: str, current_situation: str, future_plan: str) -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY chua duoc cau hinh")
    client = anthropic.Anthropic(api_key=api_key)
    user_content = f"""対象者氏名: {employee_name}

【元の入力】
{raw_text}

【AIが作成した報告書】
■ 3ヶ月間の総評:
{current_situation}

■ 今後の目標:
{future_plan}
"""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=REVIEW_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    return json.loads(raw)
