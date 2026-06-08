# config/sheet_config.py
COLOR_CELL_DONE = {"red": 1.0, "green": 0.949, "blue": 0.8}
COLOR_TAB_DONE  = {"red": 1.0, "green": 0.851, "blue": 0.4}
COLOR_TAB_ERROR = {"red": 0.957, "green": 0.694, "blue": 0.694}

ROW_DATE        = 2
ROW_CURRENT     = 31
ROW_FUTURE_STD  = 36
ROW_FUTURE_ALT  = 33

COL_CONTENT        = "B"
COL_DATE           = "E"
COL_CHECKLIST_MARK = "E"

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
        "row_future": ROW_FUTURE_ALT,
        "checklist_col_a_name": "たき航グループ 株式会社",
    },
    "WILLBE": {
        "env_key": "SHEET_WILLBE_ID",
        "row_future": ROW_FUTURE_STD,
        "checklist_col_a_name": "株式会社ウィルビー",
    },
}
