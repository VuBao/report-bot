"""Extraction and safe form updates for Japanese residence-card submissions."""

import base64
import io
import json
import logging
import os
import re
import time
import unicodedata
from datetime import date, datetime

import gspread
from google.oauth2.service_account import Credentials
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from config.sheet_config import (
    COLOR_CELL_DONE,
    FORM_ADDRESS_CELL,
    FORM_COMPANY_BRANCH_CELL,
    FORM_CURRENT_REPORT_CELL,
    FORM_DATE_CELL,
    FORM_DOB_CELL,
    FORM_FUTURE_REPORT_CELL,
    FORM_HIGHLIGHT_RANGES,
    FORM_JAPANESE_LEVEL_CELL,
    FORM_NAME_CELL,
    FORM_TEMPLATE,
    FORM_VISA_EXPIRY_CELL,
)
from utils.retry import exception_http_status, is_transient_external_error

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
# Every stored field must clear this threshold. An uncertain address in the
# full-card pass is re-read from an enlarged crop before validation. The
# sender's confirmation remains an additional safeguard, not a replacement
# for OCR confidence validation.
MIN_CONFIDENCE = 0.80
GOOGLE_WRITE_MAX_ATTEMPTS = 5
GOOGLE_WRITE_RETRY_DELAYS_SECONDS = (1, 2, 4, 8)
_DATE_RE = re.compile(r"^(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日$")
_CARD_ASPECT_RATIO = 85.60 / 53.98
_FRONT_ADDRESS_CROP = (0.02, 0.29, 0.79, 0.58)
_BACK_ADDRESS_CROP = (0.02, 0.02, 0.98, 0.53)
_ADDRESS_CROP_SCALE = 3

VISION_PROMPT = """
You extract only visual facts from one front image, or optional front and back
images, of a Japanese residence card. Return JSON only. Never infer unclear
characters. Identify a front side from its content, not image order.

Required schema:
{
  "document_type": "residence_card" | "unknown",
  "front_detected": boolean,
  "back_detected": boolean,
  "address_review_required": boolean,
  "front_image_index": integer | null,
  "back_image_index": integer | null,
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
do not use a high value for guesses. Image indexes are zero-based positions in
the supplied image list. front_image_index is required when front_detected is
true. back_image_index is required only when back_detected is true.
Set address_review_required to true if any character, digit, hyphen, apartment
number, building name, reported date, or the presence of a back-side address
entry is uncertain. Otherwise set it to false. Never hide uncertainty behind
a completed or plausible-looking address.
"""

VISION_VERIFY_PROMPT = """
You are the independent second-pass verifier for residence-card addresses.
You receive only enlarged crops of address regions, each preceded by a label
identifying FRONT or BACK. Return JSON only using exactly the schema below.
Transcribe the address text directly from these crops. Check every character,
digit, hyphen, apartment number, and Japanese building-name character. Never
complete a word or address from what seems common or plausible. If any
character is unclear, return an empty value or lower confidence instead of
guessing.

Required schema:
{
  "front_address": {"value": string, "confidence": number},
  "back_address_entries": [
    {"reported_date": "YYYY年MM月DD日" | "", "address": string, "confidence": number}
  ]
}

front_address comes only from 住居地/ADDRESS in the FRONT crop. For the BACK
crop, list only entries in 住居地記載欄. If there is no BACK crop or no address
entry, return an empty list. Do not return labels, seals, or unrelated text.
"""


def _get_client():
    creds = Credentials.from_service_account_file(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "./config/service_account.json"),
        scopes=SCOPES,
    )
    return gspread.authorize(creds)


def _google_error_status(exc):
    """Extract an HTTP status from gspread/google API exceptions when present."""
    return exception_http_status(exc)


def _is_transient_google_error(exc):
    return is_transient_external_error(exc)


def normalize_name(value):
    value = unicodedata.normalize("NFKC", value or "")
    return " ".join(value.strip().upper().split())


def _normalize_text(value):
    return " ".join((value or "").strip().split())


def _normalize_ocr_text(value):
    return unicodedata.normalize("NFKC", _normalize_text(value))


def _value(field):
    if not isinstance(field, dict):
        return "", 0.0
    value = _normalize_text(str(field.get("value", "")))
    return value, _confidence(field.get("confidence", 0))


def _confidence(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _required_value(card, field):
    value, confidence = _value(card.get(field))
    if not value or confidence < MIN_CONFIDENCE:
        raise ValueError(f"Khong the doc chac chan truong {field}; vui long chup lai the ro hon")
    return value


def _canonical_back_entries(card):
    entries = card.get("back_address_entries", [])
    if not isinstance(entries, list):
        raise ValueError("Du lieu dia chi mat sau khong hop le")

    canonical = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Du lieu dia chi mat sau khong hop le")
        canonical.append((
            _normalize_ocr_text(str(entry.get("reported_date", ""))),
            _normalize_ocr_text(str(entry.get("address", ""))),
        ))
    if len(canonical) != len(set(canonical)):
        raise ValueError("Du lieu dia chi mat sau bi trung lap")
    return sorted(canonical)


def _center_crop_card(image):
    """Crop surrounding photo margins to the centered ISO ID-1 card shape."""
    width, height = image.size
    current_ratio = width / height
    if current_ratio > _CARD_ASPECT_RATIO:
        card_width = round(height * _CARD_ASPECT_RATIO)
        left = (width - card_width) // 2
        return image.crop((left, 0, left + card_width, height))
    card_height = round(width / _CARD_ASPECT_RATIO)
    top = (height - card_height) // 2
    return image.crop((0, top, width, top + card_height))


def _crop_address_region(image_bytes, normalized_box):
    """Return an enlarged, contrast-enhanced JPEG crop of an address region."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
    except Exception as exc:
        raise ValueError("Khong the xu ly anh the de kiem tra dia chi") from exc

    card = _center_crop_card(image)
    width, height = card.size
    left, top, right, bottom = normalized_box
    crop = card.crop((
        round(width * left),
        round(height * top),
        round(width * right),
        round(height * bottom),
    ))
    crop = crop.resize(
        (crop.width * _ADDRESS_CROP_SCALE, crop.height * _ADDRESS_CROP_SCALE),
        Image.Resampling.LANCZOS,
    )
    crop = ImageOps.autocontrast(crop, cutoff=1)
    crop = ImageEnhance.Sharpness(crop).enhance(1.5)
    crop = crop.filter(ImageFilter.UnsharpMask(radius=1.2, percent=125, threshold=2))
    output = io.BytesIO()
    crop.save(output, format="JPEG", quality=95, optimize=True)
    return output.getvalue()


def _resolve_image_indexes(card, image_count):
    if not isinstance(card, dict):
        raise ValueError("AI khong tra ve du lieu the hop le")

    front_index = card.get("front_image_index")
    if front_index is None and image_count == 1 and card.get("front_detected") is True:
        front_index = 0
    if isinstance(front_index, bool) or not isinstance(front_index, int):
        raise ValueError("Khong the xac dinh anh mat truoc de crop dia chi")
    if not 0 <= front_index < image_count:
        raise ValueError("Chi so anh mat truoc khong hop le")

    back_index = card.get("back_image_index")
    if image_count == 2 and card.get("back_detected") is not True:
        # Always inspect the other supplied image as a possible back. If the
        # first pass missed a handwritten address there, the crop pass will
        # disagree and safely stop the submission.
        back_index = 1 - front_index
    elif card.get("back_detected") is True:
        if back_index is None and image_count == 2:
            back_index = 1 - front_index
        if isinstance(back_index, bool) or not isinstance(back_index, int):
            raise ValueError("Khong the xac dinh anh mat sau de crop dia chi")
        if not 0 <= back_index < image_count or back_index == front_index:
            raise ValueError("Chi so anh mat sau khong hop le")
    else:
        back_index = None
    return front_index, back_index


def _build_address_crop_content(image_bytes_list, first):
    front_index, back_index = _resolve_image_indexes(first, len(image_bytes_list))
    crops = [("FRONT ADDRESS CROP", front_index, _FRONT_ADDRESS_CROP)]
    if back_index is not None:
        crops.append(("BACK ADDRESS CROP", back_index, _BACK_ADDRESS_CROP))

    content = []
    for label, image_index, crop_box in crops:
        crop_bytes = _crop_address_region(image_bytes_list[image_index], crop_box)
        encoded = base64.b64encode(crop_bytes).decode("ascii")
        content.extend([
            {"type": "text", "text": label},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encoded}", "detail": "high"},
            },
        ])
    return content


def _back_entries_need_recheck(card):
    entries = card.get("back_address_entries", [])
    if not isinstance(entries, list):
        return True
    for entry in entries:
        if not isinstance(entry, dict):
            return True
        if (
            not _normalize_text(str(entry.get("reported_date", "")))
            or not _normalize_text(str(entry.get("address", "")))
            or _confidence(entry.get("confidence", 0)) < MIN_CONFIDENCE
        ):
            return True
    return False


def _address_needs_recheck(card):
    """Return whether the full-card result leaves any address uncertainty."""
    if not isinstance(card, dict):
        return True
    if card.get("address_review_required") is True:
        return True
    address, confidence = _value(card.get("front_address"))
    return not address or confidence < MIN_CONFIDENCE or _back_entries_need_recheck(card)


def _merge_address_recheck(first, address_check):
    """Use crop OCR to resolve uncertainty, while rejecting confident conflicts."""
    if not isinstance(first, dict) or not isinstance(address_check, dict):
        raise ValueError("AI khong tra ve du lieu dia chi hop le o ca hai lan doc")

    first_address, first_confidence = _value(first.get("front_address"))
    checked_address, checked_confidence = _value(address_check.get("front_address"))
    review_requested = first.get("address_review_required") is True
    first_front_reliable = (
        bool(first_address)
        and first_confidence >= MIN_CONFIDENCE
        and not review_requested
    )
    if (
        first_front_reliable
        and _normalize_ocr_text(first_address) != _normalize_ocr_text(checked_address)
    ):
        raise ValueError(
            "Hai lan doc the khong khop truong dia chi mat truoc; vui long chup lai the ro hon"
        )

    verified = dict(first)
    if first_front_reliable:
        verified["front_address"] = {
            "value": first_address,
            "confidence": min(first_confidence, checked_confidence),
        }
    else:
        verified["front_address"] = {
            "value": checked_address,
            "confidence": checked_confidence,
        }

    if review_requested or _back_entries_need_recheck(first):
        checked_entries = address_check.get("back_address_entries", [])
        if not isinstance(checked_entries, list):
            raise ValueError("Du lieu dia chi mat sau khong hop le")
        verified["back_address_entries"] = [
            {
                "reported_date": _normalize_text(str(entry.get("reported_date", ""))),
                "address": _normalize_text(str(entry.get("address", ""))),
                "confidence": _confidence(entry.get("confidence", 0)),
            }
            if isinstance(entry, dict) else entry
            for entry in checked_entries
        ]
    else:
        first_back_entries = _canonical_back_entries(first)
        checked_back_entries = _canonical_back_entries(address_check)
        if first_back_entries != checked_back_entries:
            raise ValueError(
                "Hai lan doc the khong khop dia chi mat sau; vui long chup lai the ro hon"
            )
        checked_back_confidence = {
            (
                _normalize_ocr_text(str(entry.get("reported_date", ""))),
                _normalize_ocr_text(str(entry.get("address", ""))),
            ): _confidence(entry.get("confidence", 0))
            for entry in address_check.get("back_address_entries", [])
        }
        verified["back_address_entries"] = []
        for entry in first.get("back_address_entries", []):
            key = (
                _normalize_ocr_text(str(entry.get("reported_date", ""))),
                _normalize_ocr_text(str(entry.get("address", ""))),
            )
            verified["back_address_entries"].append({
                "reported_date": _normalize_text(str(entry.get("reported_date", ""))),
                "address": _normalize_text(str(entry.get("address", ""))),
                "confidence": min(
                    _confidence(entry.get("confidence", 0)),
                    checked_back_confidence[key],
                ),
            })
    verified["address_review_required"] = False
    return verified


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


def _today_japanese():
    now = datetime.now()
    return f"作成日：{now.year}年{now.month:02d}月{now.day:02d}日"


def validate_card(card, submitted_name):
    """Validate all allowed values; returns only the fields permitted for storage."""
    if not isinstance(card, dict) or card.get("document_type") != "residence_card":
        raise ValueError("Anh khong duoc xac dinh chac chan la the ngoai kieu")
    if card.get("front_detected") is not True:
        raise ValueError("Can anh mat truoc the ngoai kieu ro rang")

    full_name = _required_value(card, "full_name")
    if normalize_name(full_name) != normalize_name(submitted_name):
        raise ValueError("Ho ten trong payload khong khop chinh xac voi ho ten doc tren the")

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


def _call_vision(client, model, image_content, prompt, instruction):
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": [
                    *image_content,
                    {"type": "text", "text": instruction},
                ],
            },
        ],
    )
    raw = (response.choices[0].message.content or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("AI doc the khong tra ve JSON hop le") from exc


def extract_residence_card(image_bytes_list):
    """Read the full card, re-reading enlarged address crops only if uncertain."""
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

    client = OpenAI(api_key=api_key)
    extraction_model = os.getenv(
        "OPENAI_VISION_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o")
    )
    verification_model = os.getenv("OPENAI_VISION_VERIFY_MODEL", extraction_model)
    first = _call_vision(
        client,
        extraction_model,
        image_content,
        VISION_PROMPT,
        "Extract all permitted residence-card fields using the required JSON schema.",
    )
    if not _address_needs_recheck(first):
        return first

    address_crop_content = _build_address_crop_content(image_bytes_list, first)
    address_check = _call_vision(
        client,
        verification_model,
        address_crop_content,
        VISION_VERIFY_PROMPT,
        "Independently transcribe only the address fields from these enlarged crops.",
    )
    return _merge_address_recheck(first, address_check)


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
        (1, 2, 4, 6),  # E2:F2
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


def _write_residence_card_form_once(
    spreadsheet_id,
    company_name,
    branch_name,
    card_values,
    current_situation,
    future_plan,
    japanese_level=None,
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
        FORM_DATE_CELL: _today_japanese(),
        FORM_NAME_CELL: employee_name,
        FORM_DOB_CELL: card_values["date_of_birth"],
        FORM_ADDRESS_CELL: card_values["address"],
        FORM_VISA_EXPIRY_CELL: card_values["visa_expiry"],
        FORM_CURRENT_REPORT_CELL: current_situation,
        FORM_FUTURE_REPORT_CELL: future_plan,
    }
    # Preserve a manually recorded level when the interview only mentions a
    # planned exam or study.  Write F23 only for an explicitly obtained level.
    if japanese_level:
        values[FORM_JAPANESE_LEVEL_CELL] = japanese_level
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

    # Keep personal/card fields in the original FORMAT template style.  Only
    # the revised date and the two report sections are marked as updated.
    worksheet.batch_format([
        {
            "range": cell_range,
            "format": {"backgroundColor": COLOR_CELL_DONE},
        }
        for cell_range in FORM_HIGHLIGHT_RANGES.values()
    ])
    logger.info("[RESIDENCE CARD] Form write verified for workbook=%s tab=%s", spreadsheet_id, worksheet.title)
    return {"tab_name": worksheet.title, "created": created}


def write_residence_card_form(
    spreadsheet_id,
    company_name,
    branch_name,
    card_values,
    current_situation,
    future_plan,
    japanese_level=None,
):
    """Write a form safely, retrying only transient Google API failures.

    Repeating this operation is safe: it locates an already-created employee
    tab and overwrites the same approved cells with the same values.
    """
    for attempt in range(1, GOOGLE_WRITE_MAX_ATTEMPTS + 1):
        try:
            return _write_residence_card_form_once(
                spreadsheet_id,
                company_name,
                branch_name,
                card_values,
                current_situation,
                future_plan,
                japanese_level,
            )
        except Exception as exc:
            if not _is_transient_google_error(exc) or attempt == GOOGLE_WRITE_MAX_ATTEMPTS:
                raise
            delay = GOOGLE_WRITE_RETRY_DELAYS_SECONDS[attempt - 1]
            logger.warning(
                "[RESIDENCE CARD] Google API returned %s; retry %s/%s in %ss",
                _google_error_status(exc), attempt + 1, GOOGLE_WRITE_MAX_ATTEMPTS, delay,
            )
            time.sleep(delay)
