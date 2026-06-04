# services/sheet_service.py
import os
import logging
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from config.sheet_config import (
    COLOR_CELL_DONE, COLOR_TAB_DONE,
    ROW_DATE, COL_CONTENT, COL_DATE, COL_CHECKLIST_MARK,
)

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

LABEL_CURRENT = "3ヶ月間の総評"
LABEL_FUTURE  = "今後の目標"

def _get_client():
    creds = Credentials.from_service_account_file(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "./config/service_account.json"),
        scopes=SCOPES,
    )
    return gspread.authorize(creds)

def _today_japanese():
    now = datetime.now()
    return f"作成日：{now.year}年{now.month:02d}月{now.day:02d}日"

def _col_letter_to_index(col):
    return ord(col.upper()) - ord("A") + 1

def _apply_background(worksheet, row, col, color):
    try:
        cell = f"{col}{row}"
        worksheet.format(cell, {"backgroundColor": color})
        logger.info(f"[COLOR] Tô màu ô {cell}")
    except Exception as e:
        logger.error(f"[COLOR ERROR] {e}")

def _find_worksheet(spreadsheet, tab_name):
    for ws in spreadsheet.worksheets():
        if ws.title.strip().upper() == tab_name.strip().upper():
            return ws
    return None

def _find_row_by_label(all_values, label):
    """Tìm row number (1-indexed) của ô cột A chứa label."""
    for i, row in enumerate(all_values):
        if row and label in row[0]:
            return i + 1
    return None

def process_employee_sheet(spreadsheet_id, tab_name, row_future, current_situation, future_plan):
    gc = _get_client()
    spreadsheet = gc.open_by_key(spreadsheet_id)

    worksheet = _find_worksheet(spreadsheet, tab_name)
    if worksheet is None:
        return {"success": False, "error": f"Tab {tab_name} khong ton tai.", "duplicate": False}

    all_values = worksheet.get_all_values()

    # Tự tìm row theo label
    row_current = _find_row_by_label(all_values, LABEL_CURRENT)
    row_future_found = _find_row_by_label(all_values, LABEL_FUTURE)

    if not row_current:
        return {"success": False, "error": f"Khong tim thay label '{LABEL_CURRENT}'", "duplicate": False}
    if not row_future_found:
        return {"success": False, "error": f"Khong tim thay label '{LABEL_FUTURE}'", "duplicate": False}

    logger.info(f"[ROW] {LABEL_CURRENT} → row {row_current} | {LABEL_FUTURE} → row {row_future_found}")

    col_idx = _col_letter_to_index(COL_CONTENT)
    date_col_idx = _col_letter_to_index(COL_DATE)

    # Bước 1: Ghi nội dung AI
    worksheet.update_cell(row_current, col_idx, current_situation)
    worksheet.update_cell(row_future_found, col_idx, future_plan)

    # Bước 2: Cập nhật ngày
    worksheet.update_cell(ROW_DATE, date_col_idx, _today_japanese())

    # Bước 3: Tô màu xanh nhạt
    _apply_background(worksheet, row_current, COL_CONTENT, COLOR_CELL_DONE)
    _apply_background(worksheet, row_future_found, COL_CONTENT, COLOR_CELL_DONE)
    _apply_background(worksheet, ROW_DATE, COL_DATE, COLOR_CELL_DONE)

    # Bước 4: Đổi màu tab
    try:
        spreadsheet.batch_update({"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": worksheet.id, "tabColor": COLOR_TAB_DONE},
            "fields": "tabColor"
        }}]})
        logger.info(f"[TAB COLOR] Tab đổi màu xanh dương")
    except Exception as e:
        logger.error(f"[TAB COLOR ERROR] {e}")

    return {"success": True, "error": None, "duplicate": False}

def mark_checklist(employee_name, company_key):
    gc = _get_client()
    checklist_id = os.getenv("SHEET_CHECKLIST_ID")
    tab_name = os.getenv("CHECKLIST_TAB_NAME", "CHECK LIST")

    spreadsheet = gc.open_by_key(checklist_id)
    worksheet = _find_worksheet(spreadsheet, tab_name)
    if worksheet is None:
        logger.error(f"[CHECKLIST] Tab khong tim thay")
        return False

    all_values = worksheet.get_all_values()
    col_c_idx = 2
    col_e_idx = 4

    for i, row in enumerate(all_values):
        if len(row) > col_c_idx:
            cell_name = row[col_c_idx].strip().upper()
            emp = employee_name.strip().upper()
            if cell_name and (emp in cell_name or cell_name in emp):
                row_number = i + 1
                worksheet.update_cell(row_number, col_e_idx + 1, "△")
                _apply_background(worksheet, row_number, COL_CHECKLIST_MARK, COLOR_CELL_DONE)
                logger.info(f"[CHECKLIST] Check row {row_number} cho {employee_name}")
                # Cập nhật count tại row 106
                all_e = worksheet.col_values(col_e_idx + 1)
                count_check = all_e.count("✓")
                count_triangle = all_e.count("△")
                worksheet.update_cell(106, col_e_idx + 1, f"✓{count_check} △{count_triangle}")
                return True

    logger.warning(f"[CHECKLIST] Khong tim thay {employee_name}")
    return False
