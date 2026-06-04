# services/ai_service.py
import os
import json
import anthropic

MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = """
あなたは在留資格「特定技能」に関する支援報告書（入管提出用）の作成専門家です。
支援担当者がグループチャットに送ったメモ（日本語またはベトナム語）をもとに、
入管局への提出に適した正式な報告書文章を作成してください。

【文体・トーン】
- 入管提出用の公式ビジネス文書として、敬体（です・ます調）で記述すること。
- 丁寧かつ簡潔なビジネス日本語を使用すること。
- 主語は「○○さんは」または「本人は」を使用すること。
- 感情的・主観的な表現は避け、客観的・事実ベースの記述にすること。

【入力について】
- 入力はインタビュー時の速記メモのため、誤字・略語・不明瞭な表現が含まれる場合がある。
- 文脈から明らかに推測できる内容は自然なビジネス日本語に整えてよい。
- ただし、入力に存在しない事実を追加・創作することは厳禁。
- 日付・年月・期間については入力に明記されている場合のみ記載すること。年が明記されていない場合は「〇年」と記載し、推測で補完しないこと。
- 「技能実習2号」と「特定技能2号」は全く異なる在留資格であり、絶対に混同しないこと。
- 「特定技能2号」は必ず「特定技能2号」と表記すること。「技能検定試験（GINO2級）」のような誤った表記は厳禁。
- 入力に含まれる情報は全て漏れなく出力に反映すること。家族・健康・帰国予定・資格・要望など、いかなる情報も省略しないこと。
- 各セクションの情報が多い場合は段落を増やして対応すること。情報の省略は禁止。

【出力ルール】
- 出力はJSON形式のみ。キーは "current_situation" と "future_plan" の2つのみ。
- 各セクションは3〜5文の段落で構成すること。
- マークダウン記号（```）は使わないこと。
- JSONの前後に説明文を入れないこと。

【セクション定義】
"current_situation"（3ヶ月間の総評・出来事・反省点）:
  業務内容・勤務状況・職場環境・生活状態・健康状態・課題など

"future_plan"（今後の目標・会社への提案・会社への要望）:
  今後のキャリア目標・帰国予定・資格取得計画・会社への要望・私生活の予定など

【出力例】
{
  "current_situation": "○○さんは現在、□□株式会社において安定して就労しております。業務内容については十分に習熟しており、職場環境も良好な状況です。健康状態に問題はなく、日常生活も安定しております。",
  "future_plan": "今後も引き続き日本での就労を継続する意向をお持ちです。日本語能力については○級を取得済みであり、現時点での追加取得の予定はございません。〇年〇月頃に一時帰国を予定しており、帰国期間は約〇週間を見込んでおります。"
}
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
        v = re.sub(r'特定技能2号試験\d*[級号]?\)', '特定技能2号試験', v)
        v = re.sub(r'技能検定試験.{0,20}?GINO\d.{0,5}?', '特定技能2号試験', v)
        v = re.sub(r'GINO\d[級号]?試験', '特定技能2号試験', v)
        v = re.sub(r'技能検定試験\d*[級号]?', '特定技能2号試験', v)
        result[key] = v
    if "current_situation" not in result or "future_plan" not in result:
        raise ValueError(f"Claude tra ve thieu key: {list(result.keys())}")
    return result
