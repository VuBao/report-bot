# services/sheet_service.py
import os
import logging
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from config.sheet_config import (
    COLOR_CELL_DONE, COLOR_TAB_DONE,
    ROW_DATE, COL_CONTENT, COL_DATE,
    CHECKLIST_SPREADSHEET_ID, CHECKLIST_FIRST_DATA_ROW,
    CHECKLIST_DONE_MARK, COL_CHECKLIST_EMPLOYEE_NAME,
    CHECKLIST_CIRCLE_MARK, COL_CHECKLIST_MARK, COL_CHECKLIST_NOTE,
    COL_CHECKLIST_USER_NUMBER,
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
    """Convert an A1 column letter (including multi-letter columns) to an index."""
    result = 0
    for char in col.upper():
        result = result * 26 + ord(char) - ord("A") + 1
    return result

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


def _normalise_name(value):
    return " ".join(value.strip().upper().split())


def _find_checklist_employee_row(all_values, employee_name):
    """Find an employee by name in column D of the monthly checklist."""
    name_index = _col_letter_to_index(COL_CHECKLIST_EMPLOYEE_NAME) - 1
    expected_name = _normalise_name(employee_name)

    for row_number, row in enumerate(all_values, start=1):
        if len(row) <= name_index:
            continue
        listed_name = _normalise_name(row[name_index])
        if listed_name and (expected_name in listed_name or listed_name in expected_name):
            return row_number
    return None


def _formula_argument_separator(worksheet):
    """Return the formula separator required by the spreadsheet locale."""
    try:
        locale = worksheet.spreadsheet.fetch_sheet_metadata().get("properties", {}).get("locale", "")
    except Exception as exc:
        logger.warning("[CHECKLIST] Khong doc duoc locale spreadsheet: %s", exc)
        locale = ""
    # The production checklist is vi_VN, where Sheets requires semicolons in
    # multi-argument formulas such as COUNTIF. English locales use commas.
    return ";" if locale.lower().startswith("vi") else ","


def _summary_formulas(user_range, status_range, done_mark, circle_mark, separator):
    """Build locale-correct, live summary formulas for the checklist."""
    return [
        # COUNTA counts both normal digits and full-width Japanese digits such
        # as "１" that appear in the user-number column.
        [f'="Tổng: "&COUNTA({user_range})&" user"'],
        [f'="△: "&COUNTIF({status_range}{separator}"{done_mark}")&" user"'],
        [f'="〇: "&COUNTIF({status_range}{separator}"{circle_mark}")&" user"'],
    ]


def _clear_stale_summary_formulas(worksheet, first_row):
    """Remove only old bot-generated statistics below the current roster."""
    formula_rows = worksheet.get(
        f"{COL_CHECKLIST_MARK}{first_row}:{COL_CHECKLIST_MARK}{worksheet.row_count}",
        value_render_option="FORMULA",
    )
    stale_cells = []
    for row_number, row in enumerate(formula_rows, start=first_row):
        value = row[0] if row else ""
        if isinstance(value, str) and value.startswith((
            '="Tổng: "&COUNT',
            '="△: "&COUNTIF(',
            '="〇: "&COUNTIF(',
            # Previous formula forms are also safe to remove.
            '="Tổng user: "&COUNT',
            '="Đã xử lý: "&COUNTIF(',
            '="Còn lại: "&COUNT',
        )):
            stale_cells.append(f"{COL_CHECKLIST_MARK}{row_number}")
    if stale_cells:
        worksheet.batch_clear(stale_cells)
        logger.info("[CHECKLIST] Da xoa %s cong thuc thong ke cu", len(stale_cells))


def _update_checklist_summary(worksheet, all_values):
    """Keep live totals below column G, driven by the checklist status in G.

    The formula range ends at the last roster row, so the summary cells themselves
    are never included in the totals.  Clearing or changing a status in G therefore
    updates the completed and remaining counts automatically.
    """
    number_index = _col_letter_to_index(COL_CHECKLIST_USER_NUMBER) - 1
    name_index = _col_letter_to_index(COL_CHECKLIST_EMPLOYEE_NAME) - 1
    roster_rows = [
        row_number
        for row_number, row in enumerate(all_values, start=1)
        if row_number >= CHECKLIST_FIRST_DATA_ROW
        and len(row) > number_index
        and row[number_index].strip()
        and len(row) > name_index
        and row[name_index].strip()
    ]
    if not roster_rows:
        logger.warning("[CHECKLIST] Khong co dong user de cap nhat tong hop")
        return

    last_roster_row = max(roster_rows)
    summary_row = last_roster_row + 2
    status_range = f"{COL_CHECKLIST_MARK}{CHECKLIST_FIRST_DATA_ROW}:{COL_CHECKLIST_MARK}{last_roster_row}"
    user_range = f"{COL_CHECKLIST_USER_NUMBER}{CHECKLIST_FIRST_DATA_ROW}:{COL_CHECKLIST_USER_NUMBER}{last_roster_row}"
    done_mark = CHECKLIST_DONE_MARK.replace('"', '""')
    formulas = _summary_formulas(
        user_range,
        status_range,
        done_mark,
        CHECKLIST_CIRCLE_MARK.replace('"', '""'),
        _formula_argument_separator(worksheet),
    )
    _clear_stale_summary_formulas(worksheet, last_roster_row + 1)
    worksheet.update(
        f"{COL_CHECKLIST_MARK}{summary_row}:{COL_CHECKLIST_MARK}{summary_row + 2}",
        formulas,
        value_input_option="USER_ENTERED",
    )
    logger.info("[CHECKLIST] Cap nhat tong hop tai cot %s, tu row %s", COL_CHECKLIST_MARK, summary_row)

def process_employee_sheet(spreadsheet_id, tab_name, row_future, current_situation, future_plan):
    gc = _get_client()
    spreadsheet = gc.open_by_key(spreadsheet_id)

    worksheet = _find_worksheet(spreadsheet, tab_name)
    is_new_employee = False
    if worksheet is None:
        logger.info(f"[NEW] Tab '{tab_name}' khong ton tai — tao moi tu tab cuoi")
        worksheets = spreadsheet.worksheets()
        last_sheet = worksheets[-1]
        spreadsheet.batch_update({"requests": [{"duplicateSheet": {
            "sourceSheetId": last_sheet.id,
            "insertSheetIndex": len(worksheets),
            "newSheetName": tab_name
        }}]})
        worksheet = spreadsheet.worksheet(tab_name)
        for cell_range in ["B2:D2", "B3:C3", "B4", "B5:D5"]:
            worksheet.batch_clear([cell_range])
        is_new_employee = True
        logger.info(f"[NEW] Tab '{tab_name}' da duoc tao")

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

    return {"success": True, "error": None, "duplicate": False, "is_new_employee": is_new_employee}

def mark_checklist(employee_name, company_key):
    gc = _get_client()
    # A legacy SHEET_CHECKLIST_ID may still point to the old roster.  Only an
    # explicit new override is allowed to change the configured destination.
    checklist_id = os.getenv("CHECKLIST_SPREADSHEET_ID_OVERRIDE", CHECKLIST_SPREADSHEET_ID)
    tab_name = os.getenv("CHECKLIST_TAB_NAME", "CHECK LIST")

    spreadsheet = gc.open_by_key(checklist_id)
    worksheet = _find_worksheet(spreadsheet, tab_name)
    if worksheet is None:
        logger.error(f"[CHECKLIST] Tab khong tim thay")
        return False

    all_values = worksheet.get_all_values()
    row_number = _find_checklist_employee_row(all_values, employee_name)
    if row_number:
        worksheet.update_cell(
            row_number,
            _col_letter_to_index(COL_CHECKLIST_MARK),
            CHECKLIST_DONE_MARK,
        )
        _apply_background(worksheet, row_number, COL_CHECKLIST_MARK, COLOR_CELL_DONE)
        # Reload so that a manually appended roster row is included in the totals.
        _update_checklist_summary(worksheet, worksheet.get_all_values())
        logger.info(f"[CHECKLIST] Check row {row_number} cho {employee_name}")
        return True

    logger.warning(f"[CHECKLIST] Khong tim thay {employee_name}")
    return False


def set_tab_color(spreadsheet_id, tab_name, color):
    gc = _get_client()
    spreadsheet = gc.open_by_key(spreadsheet_id)
    worksheet = _find_worksheet(spreadsheet, tab_name)
    if worksheet is None:
        logger.error(f"[TAB COLOR] Tab '{tab_name}' khong tim thay")
        return
    try:
        spreadsheet.batch_update({"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": worksheet.id, "tabColor": color},
            "fields": "tabColor"
        }}]})
        logger.info(f"[TAB COLOR] Tab '{tab_name}' doi mau")
    except Exception as e:
        logger.error(f"[TAB COLOR ERROR] {e}")


def duplicate_last_sheet(spreadsheet_id, new_tab_name):
    gc = _get_client()
    spreadsheet = gc.open_by_key(spreadsheet_id)
    worksheets = spreadsheet.worksheets()
    last_sheet = worksheets[-1]
    
    # Duplicate tab cuoi cung
    spreadsheet.batch_update({"requests": [{
        "duplicateSheet": {
            "sourceSheetId": last_sheet.id,
            "insertSheetIndex": len(worksheets),
            "newSheetName": new_tab_name
        }
    }]})
    
    # Lay tab moi
    new_ws = spreadsheet.worksheet(new_tab_name)
    
    # Xoa thong tin ca nhan
    cells_to_clear = ["B2:D2", "B3:C3", "B4", "B5:D5"]
    for cell_range in cells_to_clear:
        new_ws.batch_clear([cell_range])
    
    logger.info(f"[DUPLICATE] Tab '{new_tab_name}' da duoc tao tu '{last_sheet.title}'")
    return new_ws


def add_checklist_note(employee_name, company_name, note):
    gc = _get_client()
    checklist_id = os.getenv("CHECKLIST_SPREADSHEET_ID_OVERRIDE", CHECKLIST_SPREADSHEET_ID)
    tab_name = os.getenv("CHECKLIST_TAB_NAME", "CHECK LIST")
    spreadsheet = gc.open_by_key(checklist_id)
    worksheet = _find_worksheet(spreadsheet, tab_name)
    if worksheet is None:
        logger.error(f"[CHECKLIST NOTE] Tab khong tim thay")
        return False
    all_values = worksheet.get_all_values()
    row_number = _find_checklist_employee_row(all_values, employee_name)
    if row_number:
        worksheet.update_cell(row_number, _col_letter_to_index(COL_CHECKLIST_NOTE), note)
        logger.info(f"[CHECKLIST NOTE] Row {row_number}: {note}")
        return True
    logger.warning(f"[CHECKLIST NOTE] Khong tim thay {employee_name}")
    return False
