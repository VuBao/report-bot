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
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from config.sheet_config import (
    COLOR_CELL_DONE,
    FORM_AGE_CELL,
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
from utils.openai_compat import (
    build_chat_completion_kwargs,
    is_gpt5_model,
    reasoning_effort_from_env,
)

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
VISION_MAX_COMPLETION_TOKENS = 4000
VISION_RECOVERY_MAX_COMPLETION_TOKENS = 6000
GOOGLE_WRITE_MAX_ATTEMPTS = 5
GOOGLE_WRITE_RETRY_DELAYS_SECONDS = (1, 2, 4, 8)
_DATE_RE = re.compile(r"^(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日$")
_CARD_ASPECT_RATIO = 85.60 / 53.98
_FRONT_ADDRESS_CROP = (0.01, 0.24, 0.99, 0.66)
_BACK_ADDRESS_CROP = (0.02, 0.02, 0.98, 0.53)
_ADDRESS_CROP_SCALE = 3
_JAPAN_TIMEZONE = ZoneInfo("Asia/Tokyo")

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
  "front_address_line_count": 1 | 2 | null,
  "front_address_lines": [string],
  "back_address_entries": [
    {"reported_date": "YYYY年MM月DD日" | "", "address": string, "confidence": number}
  ],
  "visa_expiry": {"value": "YYYY年MM月DD日" | "", "confidence": number}
}

Rules: full_name comes only from 氏名/NAME. date_of_birth comes only from 生年月日/DATE OF BIRTH.
visa_expiry comes only from 在留期間満了日/THE EXPIRY DATE OF THE PERIOD OF STAY;
do not use the card-validity date. front_address comes only from 住居地/ADDRESS on the front.
The front address may wrap onto multiple printed lines (including a second line
containing Latin text, an apartment number, or a building name). Read every
line in that field through its final visible character; do not stop at the first
line or crop the value to the label area. Scan both the far-right end and the
far-left start of every visual line. A room number can split across the physical
line boundary: for example, `2` at the far right followed by `01` at the far
left is one number, `201`, and must be concatenated without a space. Otherwise
join wrapped lines with a single space. Preserve every visible character and
digit; if either fragment is unclear, require address review instead of guessing.
front_address_lines must contain the exact visible address text on each physical
line, in top-to-bottom order, excluding the 住居地/ADDRESS labels. Set
front_address_line_count to the number of those lines. The whitespace-insensitive
concatenation of front_address_lines must contain exactly the same characters
and digits as front_address.value. The supplied content includes each original
card image and an enlarged candidate front-address crop derived from that same
original. Use the enlarged crop to inspect small text; image indexes refer only
to the original images identified by their labels.
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
  "front_address_line_count": 1 | 2 | null,
  "front_address_lines": [string],
  "back_address_entries": [
    {"reported_date": "YYYY年MM月DD日" | "", "address": string, "confidence": number}
  ],
  "manual_review_required": boolean,
  "uncertain_regions": [
    {
      "image": "front" | "back",
      "x_min": integer,
      "y_min": integer,
      "x_max": integer,
      "y_max": integer
    }
  ]
}

front_address comes only from 住居地/ADDRESS in the FRONT crop. The FRONT
address may occupy two printed lines; transcribe both lines through the final
visible character. Inspect the far-right end of the upper line and then the
far-left start of the next line before finalizing the value. If consecutive
digit fragments cross that visual boundary, concatenate them as one room
number without a space (`2` + `01` becomes `201`). Otherwise join lines with a
single space. Never drop leading zeroes from the continuation fragment. For the
FRONT crop, also return each exact physical address line in
front_address_lines, top to bottom, and the matching front_address_line_count.
The whitespace-insensitive concatenation of those lines must exactly equal the
characters in front_address.value. If it does not, require manual review. For the
BACK crop, list only entries in 住居地記載欄. If there is no BACK crop or no
address entry, return an empty list. Do not return labels, seals, or unrelated
text. Coordinates are relative to the corresponding supplied crop on a
0-to-1000 scale. Set manual_review_required to true and tightly bound every
unclear character or contiguous unclear span in uncertain_regions. This
includes text that may be missing, cut off, blurred, overwritten by security
patterns, or easily confused with another Japanese/Latin character or digit.
If the address is fully legible, return false and an empty uncertain_regions
list. Never guess merely to avoid manual review.
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


def _has_suspicious_wrapped_room_fragment(address):
    """Detect a likely room number cut at a residence-card line boundary."""
    text = _normalize_ocr_text(address)
    trailing = re.search(r"\s([0-9]{1,2})$", text)
    if trailing is None:
        return False
    prefix = text[:trailing.start()]
    building_start = prefix.rfind("号")
    if building_start < 0:
        return False
    building_text = prefix[building_start + 1:]
    return any(character.isalpha() for character in building_text)


def _compact_ocr_text(value):
    """Normalize OCR text for character-coverage comparisons across line wraps."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")))


def _address_lines_complete(card):
    """Require one/two physical lines to cover every character in the final address."""
    if not isinstance(card, dict):
        return False
    lines = card.get("front_address_lines")
    line_count = card.get("front_address_line_count")
    address, _ = _value(card.get("front_address"))
    if (
        not isinstance(lines, list)
        or len(lines) not in {1, 2}
        or isinstance(line_count, bool)
        or line_count != len(lines)
        or not address
    ):
        return False
    compact_lines = [_compact_ocr_text(line) for line in lines]
    if not all(compact_lines):
        return False
    return "".join(compact_lines) == _compact_ocr_text(address)


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


def _vision_image_part(image_bytes):
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{encoded}", "detail": "high"},
    }


def _build_first_pass_image_content(image_bytes_list):
    """Pair every original with an enlarged address candidate in the same OCR call."""
    content = []
    for image_index, image_bytes in enumerate(image_bytes_list):
        content.extend([
            {"type": "text", "text": f"ORIGINAL IMAGE INDEX {image_index}"},
            _vision_image_part(image_bytes),
            {
                "type": "text",
                "text": (
                    "ENLARGED FRONT ADDRESS CANDIDATE FROM ORIGINAL "
                    f"IMAGE INDEX {image_index}"
                ),
            },
            _vision_image_part(
                _crop_address_region(image_bytes, _FRONT_ADDRESS_CROP)
            ),
        ])
    return content


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


def _build_address_crops(image_bytes_list, first):
    front_index, back_index = _resolve_image_indexes(first, len(image_bytes_list))
    crop_specs = [("front", "FRONT ADDRESS CROP", front_index, _FRONT_ADDRESS_CROP)]
    if back_index is not None:
        crop_specs.append(("back", "BACK ADDRESS CROP", back_index, _BACK_ADDRESS_CROP))

    return [
        {
            "side": side,
            "label": label,
            "bytes": _crop_address_region(image_bytes_list[image_index], crop_box),
        }
        for side, label, image_index, crop_box in crop_specs
    ]


def _address_crop_content(crops):
    content = []
    for crop in crops:
        content.extend([
            {"type": "text", "text": crop["label"]},
            _vision_image_part(crop["bytes"]),
        ])
    return content


def _build_address_crop_content(image_bytes_list, first):
    """Build vision content for tests and callers that only need the payload."""
    return _address_crop_content(_build_address_crops(image_bytes_list, first))


def _normalized_review_box(region, width, height):
    if not isinstance(region, dict):
        return None
    try:
        x_min = float(region.get("x_min"))
        y_min = float(region.get("y_min"))
        x_max = float(region.get("x_max"))
        y_max = float(region.get("y_max"))
    except (TypeError, ValueError):
        return None
    if not all(0 <= value <= 1000 for value in (x_min, y_min, x_max, y_max)):
        return None
    if x_max <= x_min or y_max <= y_min:
        return None

    padding = max(8, round(min(width, height) * 0.015))
    return (
        max(0, round(width * x_min / 1000) - padding),
        max(0, round(height * y_min / 1000) - padding),
        min(width - 1, round(width * x_max / 1000) + padding),
        min(height - 1, round(height * y_max / 1000) + padding),
    )


def _highlight_uncertain_address_regions(crops, address_check):
    """Return JPEG crops with model-reported uncertainty outlined in red."""
    regions = address_check.get("uncertain_regions", [])
    if not isinstance(regions, list):
        regions = []

    review_images = []
    for crop in crops:
        try:
            with Image.open(io.BytesIO(crop["bytes"])) as source:
                image = source.convert("RGB")
        except Exception as exc:
            raise ValueError("Khong the tao anh danh dau dia chi can kiem tra") from exc

        boxes = []
        for region in regions:
            if not isinstance(region, dict):
                continue
            if str(region.get("image", "")).strip().lower() != crop["side"]:
                continue
            box = _normalized_review_box(region, image.width, image.height)
            if box is not None:
                boxes.append(box)

        if not boxes:
            continue

        draw = ImageDraw.Draw(image)
        line_width = max(8, round(min(image.size) * 0.012))
        for box in boxes:
            draw.rectangle(box, outline=(255, 0, 0), width=line_width)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=95, optimize=True)
        review_images.append(output.getvalue())

    if not review_images and crops:
        # A model can correctly signal uncertainty yet omit usable
        # coordinates. Keep the workflow safe by marking the full front
        # address crop instead of returning no visual clue.
        fallback = next((crop for crop in crops if crop["side"] == "front"), crops[0])
        with Image.open(io.BytesIO(fallback["bytes"])) as source:
            image = source.convert("RGB")
        inset = max(8, round(min(image.size) * 0.015))
        line_width = max(8, round(min(image.size) * 0.012))
        ImageDraw.Draw(image).rectangle(
            (inset, inset, image.width - inset, image.height - inset),
            outline=(255, 0, 0),
            width=line_width,
        )
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=95, optimize=True)
        review_images.append(output.getvalue())
    return review_images


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
    return (
        not address
        or confidence < MIN_CONFIDENCE
        or not _address_lines_complete(card)
        or _has_suspicious_wrapped_room_fragment(address)
        or _back_entries_need_recheck(card)
    )


def _address_check_needs_manual_review(address_check):
    if not isinstance(address_check, dict):
        return True
    if address_check.get("manual_review_required") is not False:
        return True
    regions = address_check.get("uncertain_regions", [])
    if not isinstance(regions, list) or regions:
        return True
    address, confidence = _value(address_check.get("front_address"))
    return (
        not address
        or confidence < MIN_CONFIDENCE
        or not _address_lines_complete(address_check)
        or _has_suspicious_wrapped_room_fragment(address)
        or _back_entries_need_recheck(address_check)
    )


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
        and _address_lines_complete(first)
        and not _has_suspicious_wrapped_room_fragment(first_address)
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
        verified["front_address_line_count"] = address_check.get(
            "front_address_line_count"
        )
        verified["front_address_lines"] = address_check.get("front_address_lines")

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
    verified["address_review_required"] = _address_check_needs_manual_review(address_check)
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


def _japan_today():
    return datetime.now(_JAPAN_TIMEZONE).date()


def _today_japanese(on_date=None):
    current_date = on_date or _japan_today()
    return (
        f"作成日：{current_date.year}年"
        f"{current_date.month:02d}月{current_date.day:02d}日"
    )


def _calculate_age(date_of_birth, on_date=None):
    """Return full years of age; increment only on/after that year's birthday."""
    canonical = _parse_japanese_date(date_of_birth, "Ngay sinh")
    match = _DATE_RE.fullmatch(canonical)
    birth_date = date(**{
        key: int(part) for key, part in match.groupdict().items()
    })
    reference_date = on_date or _japan_today()
    if birth_date > reference_date:
        raise ValueError("Ngay sinh khong the nam trong tuong lai")
    birthday_reached = (reference_date.month, reference_date.day) >= (
        birth_date.month,
        birth_date.day,
    )
    return reference_date.year - birth_date.year - (not birthday_reached)


def validate_card(card, submitted_name, *, allow_uncertain_address=False):
    """Validate all allowed values; returns only the fields permitted for storage."""
    if not isinstance(card, dict) or card.get("document_type") != "residence_card":
        raise ValueError("Anh khong duoc xac dinh chac chan la the ngoai kieu")
    if card.get("front_detected") is not True:
        raise ValueError("Can anh mat truoc the ngoai kieu ro rang")

    full_name = _required_value(card, "full_name")
    if normalize_name(full_name) != normalize_name(submitted_name):
        raise ValueError("Ho ten trong payload khong khop chinh xac voi ho ten doc tren the")

    dob = _parse_japanese_date(_required_value(card, "date_of_birth"), "Ngay sinh")
    age = _calculate_age(dob)
    visa_expiry = _parse_japanese_date(_required_value(card, "visa_expiry"), "Han visa")
    if allow_uncertain_address:
        front_address, _ = _value(card.get("front_address"))
        return {
            "full_name": full_name,
            "date_of_birth": dob,
            "age": age,
            "address": front_address,
            "visa_expiry": visa_expiry,
        }

    front_address = _required_value(card, "front_address")
    if not _address_lines_complete(card):
        raise ValueError(
            "Dia chi mat truoc khong khop du ky tu giua cac dong; vui long kiem tra lai"
        )
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
        "age": age,
        "address": address,
        "visa_expiry": visa_expiry,
    }


def _call_vision(
    client,
    model,
    image_content,
    prompt,
    instruction,
    *,
    reasoning_effort,
):
    messages = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": [
                *image_content,
                {"type": "text", "text": instruction},
            ],
        },
    ]
    attempts = [(reasoning_effort, VISION_MAX_COMPLETION_TOKENS)]
    # GPT-5 can spend the whole completion budget on hidden reasoning and
    # return empty content. Retry only that failed request with minimal
    # reasoning, leaving the normal one/two-pass OCR policy unchanged.
    if is_gpt5_model(model):
        attempts.append(("minimal", VISION_RECOVERY_MAX_COMPLETION_TOKENS))

    last_error = None
    for attempt_number, (effort, token_budget) in enumerate(attempts, start=1):
        response = client.chat.completions.create(**build_chat_completion_kwargs(
            model=model,
            max_tokens=token_budget,
            temperature=0,
            reasoning_effort=effort,
            messages=messages,
        ))
        choice = response.choices[0]
        raw = (choice.message.content or "").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            last_error = exc
            usage = getattr(response, "usage", None)
            completion_tokens = getattr(usage, "completion_tokens", None)
            details = getattr(usage, "completion_tokens_details", None)
            reasoning_tokens = getattr(details, "reasoning_tokens", None)
            logger.warning(
                "[CARD OCR] Invalid JSON response; attempt=%s/%s "
                "finish_reason=%s empty=%s completion_tokens=%s reasoning_tokens=%s",
                attempt_number,
                len(attempts),
                getattr(choice, "finish_reason", None),
                not bool(raw),
                completion_tokens,
                reasoning_tokens,
            )

    raise ValueError(
        "AI doc the khong tra ve JSON hop le sau khi thu lai"
    ) from last_error


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

    image_content = _build_first_pass_image_content(image_bytes_list)

    client = OpenAI(api_key=api_key)
    extraction_model = os.getenv(
        "OPENAI_VISION_MODEL", os.getenv("OPENAI_MODEL", "gpt-5")
    )
    verification_model = os.getenv("OPENAI_VISION_VERIFY_MODEL", extraction_model)
    first = _call_vision(
        client,
        extraction_model,
        image_content,
        VISION_PROMPT,
        "Extract all permitted residence-card fields using the required JSON schema.",
        reasoning_effort=reasoning_effort_from_env(
            "OPENAI_VISION_REASONING_EFFORT", "low"
        ),
    )
    if not _address_needs_recheck(first):
        return first

    address_crops = _build_address_crops(image_bytes_list, first)
    address_crop_content = _address_crop_content(address_crops)
    address_check = _call_vision(
        client,
        verification_model,
        address_crop_content,
        VISION_VERIFY_PROMPT,
        "Independently transcribe only the address fields from these enlarged crops.",
        reasoning_effort=reasoning_effort_from_env(
            "OPENAI_VISION_VERIFY_REASONING_EFFORT", "low"
        ),
    )
    merged = _merge_address_recheck(first, address_check)
    if merged.get("address_review_required") is True:
        merged["_address_review_images"] = _highlight_uncertain_address_regions(
            address_crops, address_check
        )
    return merged


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
    labels = worksheet.batch_get(["A2", "A3", "A4", "A5", "D4", "E4"])
    expected = ("会社名", "特定技能", "生年月日", "現在の住所", "才", "ビザ期限")
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

    report_date = _japan_today()
    values = {
        FORM_COMPANY_BRANCH_CELL: f"{company_name}     {branch_name}",
        FORM_DATE_CELL: _today_japanese(report_date),
        FORM_NAME_CELL: employee_name,
        FORM_DOB_CELL: card_values["date_of_birth"],
        FORM_AGE_CELL: str(_calculate_age(card_values["date_of_birth"], report_date)),
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
