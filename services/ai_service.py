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

【今後の目標・希望】に含める内容：
日本語目標／資格取得予定／キャリア目標／給与・条件改善希望／帰国予定／将来計画

【出力ルール】
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
