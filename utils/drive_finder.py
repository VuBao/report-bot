# utils/drive_finder.py
import os, logging, re
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/drive.readonly","https://www.googleapis.com/auth/spreadsheets"]
DEFAULT_FOLDER_ID = "18YPY8be9mS0uHA5K2csUv5_cOb2RO6hC"
_cache = {}
_files_cache = None

def _get_drive_service():
    try:
        from googleapiclient.discovery import build
    except ImportError as e:
        raise RuntimeError("Thieu dependency google-api-python-client. Hay cai lai requirements.txt") from e
    creds = Credentials.from_service_account_file(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON","./config/service_account.json"),scopes=SCOPES)
    return build("drive","v3",credentials=creds)

def _get_all_files():
    global _files_cache
    if _files_cache is not None:
        return _files_cache
    try:
        service = _get_drive_service()
        folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", DEFAULT_FOLDER_ID)
        files = []
        page_token = None
        while True:
            results = service.files().list(
                q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
                fields="nextPageToken, files(id, name)",
                pageSize=1000,
                pageToken=page_token,
            ).execute()
            files.extend(results.get("files",[]))
            page_token = results.get("nextPageToken")
            if not page_token:
                break
        _files_cache = files
        logger.info(f"[DRIVE] Loaded {len(_files_cache)} files")
        return _files_cache
    except Exception as e:
        logger.exception(f"[DRIVE ERROR] {e}")
        raise RuntimeError(f"Loi Google Drive: {e}") from e

def _normalize(text):
    import unicodedata
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'[\s　・\-—–･．。、,./\\]','',text).upper()
    # Xoa 株式会社 va cac prefix/suffix pho bien
    text = re.sub(r'(株式会社|有限会社|合同会社)', '', text)
    # Xoa ten chi nhanh (店・支店・本店・店舗・営業所)
    text = re.sub(r'[^　-鿿]*?(店|支店|本店|店舗|営業所)$', '', text)
    return text

def find_spreadsheet_id(company_name):
    key = _normalize(company_name)
    if key in _cache:
        return _cache[key]
    files = _get_all_files()
    best_match = None
    best_score = 0
    for f in files:
        file_norm = _normalize(f["name"])
        if key == file_norm:
            _cache[key] = (f["id"],f["name"])
            logger.info(f"[DRIVE EXACT] {f['name']}")
            return (f["id"],f["name"])
        if key in file_norm or file_norm in key:
            score = min(len(key),len(file_norm))
            if score > best_score:
                best_score = score
                best_match = f
    if best_match:
        _cache[key] = (best_match["id"],best_match["name"])
        logger.info(f"[DRIVE PARTIAL] {best_match['name']}")
        return (best_match["id"],best_match["name"])
    logger.warning(f"[DRIVE] Khong tim thay '{company_name}'")
    return (None,None)

def clear_cache():
    global _files_cache
    _cache.clear()
    _files_cache = None
