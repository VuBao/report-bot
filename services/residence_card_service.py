"""Extraction and safe form updates for Japanese residence-card submissions."""

import base64
import json
import logging
import os
import re
import unicodedata
from datetime import date, datetime

import gspread
from google.oauth2.service_account import Credentials

from config.sheet_config import (
    FORM_ADDRESS_CELL,
    FORM_COMPANY_BRANCH_CELL,
    FORM_CURRENT_REPORT_CELL,
    FORM_DOB_CELL,
    FORM_FUTURE_REPORT_CELL,
    FORM_NAME_CELL,
    FORM_TEMPLATE,
    FORM_VISA_EXPIRY_CELL,
)

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
# The sender reviews every extracted value and must explicitly confirm before
# writing.  A 0.98 threshold was unnecessarily strict for otherwise legible
# residence-card addresses, causing needless resubmissions.
MIN_CONFIDENCE = 0.80
_DATE_RE = re.compile(r"^(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日$")

VISION_PROMPT = """
You extract only visual facts from one front image, or optional front and back
images, of a Japanese residence card. Return JSON only. Never infer unclear
characters. Identify a front side from its content, not image order.

Required schema:
{
  "document_type": "residence_card" | "unknown",
  "front_detected": boolean,
  "back_detected": boolean,
  "full_name": {"value": string, "confidence": number},
  "date_of_birth": {"value": "YYYY年MM月DD日" | "", "confidence": number},
  "front_address": {"value": string, "confidence": number},
  "back_address_entries": [
    {"reported_date": "YYYY年MM月DD日" | "", "address": string, "confidence": number}
  ],
  "visa_expiry": {"value": "YYYY年MM月DD日" | "", "confidence": number}
}

Rules: full_name comes only from 氏名/NAME. date_of_birth comes only from 生年月日/DATE OF BIRTH.
visa_expiry comes only from 在留期間満了日/THE EXPIRY DATE OF THE PERIOD OF STAY;
do not use the card-validity date. front_address comes only from 住居地/ADDRESS on the front.
For the optional back, list only clearly handwritten/printed entries in 住居地記載欄.
If no back or no entry, return an empty list. confidence must reflect legibility;
do not use a high value for guesses.
"""


def _get_client():
    creds = Credentials.from_service_account_file(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "./config/service_account.json"),
        scopes=SCOPES,
    )
    return gspread.authorize(creds)


def normalize_name(value):
    value = unicodedata.normalize("NFKC", value or "")
    return " ".join(value.strip().upper().split())


def _normalize_text(value):
    return " ".join((value or "").strip().split())


def _value(field):
    if not isinstance(field, dict):
        return "", 0.0
    value = _normalize_text(str(field.get("value", "")))
    try:
        confidence = float(field.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    return value, confidence


def _required_value(card, field):
    value, confidence = _value(card.get(field))
    # An address is always displayed in the preview and requires the sender's
    # explicit confirmation before it is stored.  Do not force a new photo
    # merely because the vision model assigned a conservative confidence score.
    if not value or (field != "front_address" and confidence < MIN_CONFIDENCE):
        raise ValueError(f"Khong the doc chac chan truong {field}; vui long chup lai the ro hon")
    return value


def _parse_japanese_date(value, field, *, allow_past=True):
    match = _DATE_RE.fullmatch(value)
    if not match:
        raise ValueError(f"{field} khong dung dinh dang ngay YYYY年MM月DD日")
    try:
        parsed = date(**{key: int(part) for key, part in match.groupdict().items()})
    except ValueError as exc:
        raise ValueError(f"{field} khong phai ngay hop le") from exc
    if not allow_past and parsed < date.today():
        raise ValueError("Han visa tren the da qua; vui long kiem tra lai anh")
    return f"{parsed.year:04d}年{parsed.month:02d}月{parsed.day:02d}日"


def validate_card(card, submitted_name):
    """Validate all allowed values; returns only the fields permitted for storage."""
    if not isinstance(card, dict) or card.get("document_type") != "residence_card":
        raise ValueError("Anh khong duoc xac dinh chac chan la the ngoai kieu")
    if card.get("front_detected") is not True:
        raise ValueError("Can anh mat truoc the ngoai kieu ro rang")

    full_name = _required_value(card, "full_name")
    if normalize_name(full_name) != normalize_name(submitted_name):
        raise ValueError("Ho ten dong 2 khong khop chinh xac voi ho ten doc tren the")

    dob = _parse_japanese_date(_required_value(card, "date_of_birth"), "Ngay sinh")
    visa_expiry = _parse_japanese_date(_required_value(card, "visa_expiry"), "Han visa")
    front_address = _required_value(card, "front_address")
    back_entries = card.get("back_address_entries", [])
    if not isinstance(back_entries, list):
        raise ValueError("Du lieu dia chi mat sau khong hop le")

    valid_back_entries = []
    for entry in back_entries:
        if not isinstance(entry, dict):
            raise ValueError("Du lieu dia chi mat sau khong hop le")
        address = _normalize_text(str(entry.get("address", "")))
        reported_date = _normalize_text(str(entry.get("reported_date", "")))
        try:
            confidence = float(entry.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        # If Vision sees a back-side entry, every component must be unambiguous.
        if not address or not reported_date or confidence < MIN_CONFIDENCE:
            raise ValueError("Dia chi ghi o mat sau khong du ro de xac dinh an toan")
        parsed_date = _parse_japanese_date(reported_date, "Ngay thay doi dia chi")
        valid_back_entries.append((parsed_date, address))

    address = front_address
    if valid_back_entries:
        address = max(valid_back_entries, key=lambda entry: entry[0])[1]

    return {
        "full_name": full_name,
        "date_of_birth": dob,
        "address": address,
        "visa_expiry": visa_expiry,
    }


def extract_residence_card(image_bytes_list):
    """Call the configured vision-capable OpenAI model and return untrusted JSON."""
    if len(image_bytes_list) not in {1, 2}:
        raise ValueError("Can 01 anh mat truoc, hoac toi da 02 anh the ngoai kieu")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("Can cau hinh OPENAI_API_KEY de doc anh the")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Thieu dependency openai") from exc

    image_content = []
    for image_bytes in image_bytes_list:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        image_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{encoded}", "detail": "high"},
        })
    image_content.append({"type": "text", "text": "Extract the residence-card fields using the required JSON schema."})

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_VISION_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o")),
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": VISION_PROMPT},
            {"role": "user", "content": image_content},
        ],
    )
    raw = (response.choices[0].message.content or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("AI doc the khong tra ve JSON hop le") from exc


def _find_worksheet_exact(spreadsheet, employee_name):
    expected = normalize_name(employee_name)
    matches = [ws for ws in spreadsheet.worksheets() if normalize_name(ws.title) == expected]
    if len(matches) > 1:
        raise ValueError("Co nhieu tab trung ten ung vien sau chuan hoa")
    return matches[0] if matches else None


def _duplicate_template(spreadsheet, employee_name):
    template_name = FORM_TEMPLATE
    template = next(
        (ws for ws in spreadsheet.worksheets() if ws.title.strip().upper() == template_name), None
    )
    if template is None:
        raise ValueError(f"Khong tim thay template {template_name}")
    worksheets = spreadsheet.worksheets()
    spreadsheet.batch_update({"requests": [{"duplicateSheet": {
        "sourceSheetId": template.id,
        "insertSheetIndex": len(worksheets),
        "newSheetName": employee_name,
    }}]})
    return spreadsheet.worksheet(employee_name)


def _has_merge(metadata_sheet, start_row, end_row, start_col, end_col):
    expected = {
        "startRowIndex": start_row,
        "endRowIndex": end_row,
        "startColumnIndex": start_col,
        "endColumnIndex": end_col,
    }
    # Google returns a ``sheetId`` alongside the merge bounds.  Compare the
    # bounds explicitly so a valid merge is not rejected because of that
    # unrelated metadata field.
    return any(
        all(merge.get(key) == value for key, value in expected.items())
        for merge in metadata_sheet.get("merges", [])
    )


def _value_range_values(value_range):
    """Return cell values from gspread's dict or ValueRange response."""
    if isinstance(value_range, dict):
        return value_range.get("values") or []
    return list(value_range)


def _value_range_name(value_range):
    """Return the A1 range from gspread's dict or ValueRange response."""
    if isinstance(value_range, dict):
        return value_range.get("range", "")
    return getattr(value_range, "range", "")


def _verify_form_layout(spreadsheet, worksheet):
    metadata = spreadsheet.fetch_sheet_metadata(params={"includeGridData": "false"})
    sheet_metadata = next(
        (sheet for sheet in metadata.get("sheets", [])
         if sheet.get("properties", {}).get("sheetId") == worksheet.id),
        None,
    )
    if sheet_metadata is None:
        raise ValueError("Khong the xac minh cau truc tab form")
    required_merges = (
        (1, 2, 1, 4),  # B2:D2
        (2, 3, 1, 3),  # B3:C3
        (4, 5, 1, 4),  # B5:D5
        (4, 5, 4, 6),  # E5:F5
    )
    if not all(_has_merge(sheet_metadata, *merge) for merge in required_merges):
        raise ValueError("Cau truc merge cua form khong dung mau da duyet")
    labels = worksheet.batch_get(["A2", "A3", "A4", "A5", "E4"])
    expected = ("会社名", "特定技能", "生年月日", "現在の住所", "ビザ期限")
    values = [" ".join((_value_range_values(part) or [[""]])[0]) for part in labels]
    if any(label not in value for label, value in zip(expected, values)):
        raise ValueError("Nhan cua form khong dung mau da duyet")
    if worksheet.row_count < 33:
        raise ValueError("Form khong co du hang B31/B33")


def write_residence_card_form(
    spreadsheet_id,
    company_name,
    branch_name,
    card_values,
    current_situation,
    future_plan,
):
    """Create/select the exact employee tab, write all fields, then verify read-back."""
    gc = _get_client()
    spreadsheet = gc.open_by_key(spreadsheet_id)
    employee_name = card_values["full_name"]
    worksheet = _find_worksheet_exact(spreadsheet, employee_name)
    created = worksheet is None
    if created:
        worksheet = _duplicate_template(spreadsheet, employee_name)
    _verify_form_layout(spreadsheet, worksheet)

    values = {
        FORM_COMPANY_BRANCH_CELL: f"{company_name}     {branch_name}",
        FORM_NAME_CELL: employee_name,
        FORM_DOB_CELL: card_values["date_of_birth"],
        FORM_ADDRESS_CELL: card_values["address"],
        FORM_VISA_EXPIRY_CELL: card_values["visa_expiry"],
        FORM_CURRENT_REPORT_CELL: current_situation,
        FORM_FUTURE_REPORT_CELL: future_plan,
    }
    worksheet.batch_update([
        {"range": cell, "values": [[value]]}
        for cell, value in values.items()
    ], value_input_option="USER_ENTERED")
    read_back = worksheet.batch_get(list(values))
    for cell, expected in values.items():
        result = next((item for item in read_back if _value_range_name(item).endswith(cell)), None)
        actual_values = _value_range_values(result) if result is not None else []
        actual = actual_values[0][0] if actual_values and actual_values[0] else ""
        if actual != expected:
            raise RuntimeError("Xac minh sau khi ghi that bai; vui long kiem tra form truoc khi gui lai")
    logger.info("[RESIDENCE CARD] Form write verified for workbook=%s tab=%s", spreadsheet_id, worksheet.title)
    return {"tab_name": worksheet.title, "created": created}
