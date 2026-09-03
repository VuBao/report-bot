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

# CHECK LIST layout (the shared monthly roster sheet).
# B: company, C: user number, D: employee name, E: note, F: location, G: status
CHECKLIST_SPREADSHEET_ID = "1WszmJ-IwtbwzzkTQ0N7SeEtyPllQRKOX_H3JYdEG4ao"
COL_CHECKLIST_USER_NUMBER = "C"
COL_CHECKLIST_EMPLOYEE_NAME = "D"
COL_CHECKLIST_NOTE = "E"
COL_CHECKLIST_MARK = "G"
CHECKLIST_FIRST_DATA_ROW = 3
CHECKLIST_DONE_MARK = "△"

# Residence-card report form (per employee tab).
FORM_COMPANY_BRANCH_CELL = "B2"
FORM_NAME_CELL = "B3"
FORM_DOB_CELL = "B4"
FORM_ADDRESS_CELL = "B5"
FORM_VISA_EXPIRY_CELL = "E5"
FORM_CURRENT_REPORT_CELL = "B31"
FORM_FUTURE_REPORT_CELL = "B33"
FORM_MALE_TEMPLATE = "MALE"
FORM_FEMALE_TEMPLATE = "FEMALE"
COPY_TEMPLATE_SPREADSHEET_ID = "1AmqZyGFUGETnWJdRzOJ1yR2A1Y8NUwfOouhN9MKXGbw"

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
