# config/sheet_config.py
# ============================================================
# SHEET CONFIG — mapping công ty ↔ spreadsheet ↔ vị trí ô
# ============================================================

# Màu sắc (RGB tuple cho gspread)
COLOR_CELL_DONE = {"red": 0.678, "green": 0.847, "blue": 0.902    "WILLBE": {
        "env_key": "SHEET_WILLBE_ID",
        "checklist_col_a_name": "株式会社ウィルビー",
    },
}   # xanh nhạt #ADD7E6
COLOR_TAB_DONE  = {"red": 0.267, "green": 0.533, "blue": 0.800}   # xanh dương #4488CC

# Hàng chứa dữ liệu trong sheet thực thi
ROW_DATE        = 2    # E2 — ngày tạo báo cáo (作成日)
ROW_CURRENT     = 31   # B31 — tình hình hiện tại (3ヶ月間の総評)
ROW_FUTURE_STD  = 36   # B36 — định hướng tương lai (Cty 1 & 2)
ROW_FUTURE_ALT  = 33   # B33 — định hướng tương lai (Cty 3 — たき航)

# Cột trong sheet thực thi
COL_CONTENT     = "B"   # cột B — nội dung
COL_DATE        = "E"   # cột E — ngày

# Cột check trong CHECK LIST
COL_CHECKLIST_MARK = "E"

# Mapping: spreadsheet_env_key → config
COMPANY_SHEETS = {
    "RAMURA": {
        "env_key": "SHEET_RAMURA_ID",
        "row_future": ROW_FUTURE_STD,
        "checklist_col_a_name": "株式会社ラムラ",
    },
    "BICHO": {
        "env_key": "SHEET_BICHO_ID",
        "row_future": ROW_FUTURE_STD,
        "checklist_col_a_name": "株式会社 備長",
    },
    "TAKIKO": {
        "env_key": "SHEET_TAKIKO_ID",
        "row_future": ROW_FUTURE_ALT,   # Cty 3 dùng B33
        "checklist_col_a_name": "たき航グループ 株式会社",
    },
}
