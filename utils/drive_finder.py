# utils/drive_finder.py
import difflib
import logging
import os
import re
from google.oauth2.service_account import Credentials
from config.sheet_config import COPY_TEMPLATE_SPREADSHEET_ID

logger = logging.getLogger(__name__)
# Drive write permission is needed only when a missing company workbook is
# created by copying the approved COPY template.
SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]
DEFAULT_FOLDER_ID = "18YPY8be9mS0uHA5K2csUv5_cOb2RO6hC"
_cache = {}
_files_cache = None
_SPREADSHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"
_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

def _get_drive_service():
    try:
        from googleapiclient.discovery import build
    except ImportError as e:
        raise RuntimeError("Thieu dependency google-api-python-client. Hay cai lai requirements.txt") from e
    creds = Credentials.from_service_account_file(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON","./config/service_account.json"),scopes=SCOPES)
    return build("drive","v3",credentials=creds)

def _list_supported_children(service, folder_id):
    """List spreadsheet and folder children of one Drive folder."""
    children = []
    page_token = None
    while True:
        results = service.files().list(
            q=(
                f"'{folder_id}' in parents and trashed=false and "
                f"(mimeType='{_SPREADSHEET_MIME_TYPE}' or "
                f"mimeType='{_FOLDER_MIME_TYPE}')"
            ),
            fields="nextPageToken, files(id, name, mimeType)",
            pageSize=1000,
            pageToken=page_token,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        ).execute()
        children.extend(results.get("files", []))
        page_token = results.get("nextPageToken")
        if not page_token:
            return children


def _get_all_files():
    """Return every company spreadsheet below the configured Drive folder."""
    global _files_cache
    if _files_cache is not None:
        return _files_cache
    try:
        service = _get_drive_service()
        root_folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", DEFAULT_FOLDER_ID)
        files = []
        pending_folder_ids = [root_folder_id]
        visited_folder_ids = set()
        seen_file_ids = set()

        while pending_folder_ids:
            folder_id = pending_folder_ids.pop()
            if folder_id in visited_folder_ids:
                continue
            visited_folder_ids.add(folder_id)

            for child in _list_supported_children(service, folder_id):
                if child.get("mimeType") == _FOLDER_MIME_TYPE:
                    pending_folder_ids.append(child["id"])
                elif child["id"] not in seen_file_ids:
                    seen_file_ids.add(child["id"])
                    files.append({"id": child["id"], "name": child["name"]})

        _files_cache = files
        logger.info(
            "[DRIVE] Loaded %s files from %s folders",
            len(_files_cache),
            len(visited_folder_ids),
        )
        return _files_cache
    except Exception as e:
        logger.exception(f"[DRIVE ERROR] {e}")
        raise RuntimeError(f"Loi Google Drive: {e}") from e

def _normalize(text):
    import unicodedata
    text = unicodedata.normalize('NFKC', text)
    # Normalize hiragana to katakana so ラーメン and らーめん can match.
    text = ''.join(chr(ord(ch) + 0x60) if 'ぁ' <= ch <= 'ゖ' else ch for ch in text)
    text = re.sub(r'[\s　・\-—–･．。、,./\\]','',text).upper()
    # Xoa 株式会社 va cac prefix/suffix pho bien
    text = re.sub(r'(株式会社|有限会社|合同会社)', '', text)
    # Xoa ten chi nhanh (店・支店・本店・店舗・営業所)
    text = re.sub(r'[^　-鿿]*?(店|支店|本店|店舗|営業所)$', '', text)
    return text

def _match_score(key, file_norm):
    if key == file_norm:
        return 1000
    if key in file_norm or file_norm in key:
        return 800 + min(len(key), len(file_norm))
    common_chars = sum(min(key.count(ch), file_norm.count(ch)) for ch in set(key))
    coverage = common_chars / max(len(key), 1)
    similarity = difflib.SequenceMatcher(None, key, file_norm).ratio()
    if coverage >= 0.75 and similarity >= 0.55:
        return int(coverage * 100 + similarity * 100)
    return 0

def find_spreadsheet_id(company_name):
    key = _normalize(company_name)
    if key in _cache:
        return _cache[key]
    files = _get_all_files()
    best_match = None
    best_score = 0
    for f in files:
        file_norm = _normalize(f["name"])
        score = _match_score(key, file_norm)
        if score >= 1000:
            _cache[key] = (f["id"],f["name"])
            logger.info(f"[DRIVE EXACT] {f['name']}")
            return (f["id"],f["name"])
        if score > best_score:
            best_score = score
            best_match = f
    if best_match:
        _cache[key] = (best_match["id"],best_match["name"])
        logger.info(f"[DRIVE MATCH] {best_match['name']} score={best_score}")
        return (best_match["id"],best_match["name"])
    logger.warning(f"[DRIVE] Khong tim thay '{company_name}'")
    return (None,None)


def find_spreadsheet_id_strict(company_name):
    """Find a company workbook, accepting one unambiguous close match for card data."""
    key = _normalize(company_name)
    matches = [file for file in _get_all_files() if _normalize(file["name"]) == key]
    if len(matches) == 1:
        file = matches[0]
        logger.info("[DRIVE STRICT] Found one exact company workbook")
        return file["id"], file["name"]
    if len(matches) > 1:
        raise ValueError("Co nhieu file Google Sheet trung ten cong ty; khong the chon an toan")

    # Company names in Telegram often differ from Drive filenames only by
    # punctuation, spacing, or a branch suffix.  Accept the closest match when
    # it is unambiguous; never silently pick between equally good candidates.
    scored_matches = [
        (_match_score(key, _normalize(file["name"])), file)
        for file in _get_all_files()
    ]
    scored_matches = [(score, file) for score, file in scored_matches if score > 0]
    if not scored_matches:
        logger.warning("[DRIVE STRICT] No workbook or close match for company")
        return None, None

    best_score = max(score for score, _ in scored_matches)
    best_matches = [file for score, file in scored_matches if score == best_score]
    if len(best_matches) != 1:
        raise ValueError("Co nhieu Google Sheet gan dung ten cong ty; khong the chon an toan")

    file = best_matches[0]
    logger.info("[DRIVE CLOSE MATCH] Selected %s (score=%s)", file["name"], best_score)
    return file["id"], file["name"]


def find_or_create_company_spreadsheet(company_name):
    """Return the exact company workbook, copying COPY into the Drive folder if absent."""
    # Always reconcile against Drive immediately before a non-idempotent copy.
    # A previous copy request may have reached Google even if its response
    # timed out, while the process-level listing cache still says it is absent.
    clear_cache()
    spreadsheet_id, file_name = find_spreadsheet_id_strict(company_name)
    if spreadsheet_id:
        return spreadsheet_id, file_name, False

    service = _get_drive_service()
    folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", DEFAULT_FOLDER_ID)
    try:
        copied = service.files().copy(
            fileId=COPY_TEMPLATE_SPREADSHEET_ID,
            body={"name": company_name, "parents": [folder_id]},
            fields="id,name",
        ).execute()
    except Exception:
        # Force the next XAC NHAN to discover a copy that Google may have
        # completed despite a lost/timed-out response.
        clear_cache()
        raise
    clear_cache()
    logger.info("[DRIVE COPY] Created company workbook from COPY template")
    return copied["id"], copied["name"], True

def clear_cache():
    global _files_cache
    _cache.clear()
    _files_cache = None
