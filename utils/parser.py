# utils/parser.py
# ============================================================
# PARSER — nhận dạng công ty và ứng viên từ message Telegram
# ============================================================

import os
import re
from config.sheet_config import COMPANY_SHEETS

# Map keyword → company key
COMPANY_KEYWORDS = {
    "ラムラ":   "RAMURA",
    "ramura":  "RAMURA",
    "備長":    "BICHO",
    "bicho":   "BICHO",
    "たき航":  "TAKIKO",
    "takiko":  "TAKIKO",
    "taki":    "TAKIKO",
}


def detect_company(text: str) -> str | None:
    """
    Tìm tên công ty từ nội dung message.
    Trả về company_key (RAMURA / BICHO / TAKIKO) hoặc None.
    """
    lower = text.lower()
    for keyword, key in COMPANY_KEYWORDS.items():
        if keyword.lower() in lower:
            return key
    return None


def detect_employee_name(text: str) -> str | None:
    """
    Tìm tên ứng viên (dạng NGUYEN VAN A) từ nội dung message.
    Ưu tiên tìm pattern: chữ hoa liên tiếp ≥ 2 từ.
    """
    # Pattern: 2–5 từ chữ hoa liên tiếp (tên tiếng Việt/Nhật dạng Latin)
    pattern = r"\b([A-Z]{2,}(?:\s+[A-Z]{2,}){1,4})\b"
    matches = re.findall(pattern, text)
    if matches:
        # Trả về tên dài nhất (nhiều từ nhất)
        return max(matches, key=lambda m: len(m.split()))
    return None


def get_spreadsheet_id(company_key: str) -> str | None:
    """Lấy spreadsheet ID từ env theo company_key."""
    config = COMPANY_SHEETS.get(company_key)
    if not config:
        return None
    return os.getenv(config["env_key"])


def get_row_future(company_key: str) -> int:
    """Lấy số hàng cho ô định hướng tương lai theo công ty."""
    config = COMPANY_SHEETS.get(company_key)
    if not config:
        return 36  # default
    return config["row_future"]
