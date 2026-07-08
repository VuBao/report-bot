import re

EMPLOYEE_NAME_RE = re.compile(r"\b([A-Z]{2,}(?:\s+[A-Z]{2,}){1,4})\b")

def _is_employee_name(line):
    parts = line.strip().split()
    return len(parts) >= 2 and bool(re.fullmatch(r"[A-Z\s]+", line.strip()))

def _strip_employee_name_from_company_line(line):
    """Handle formats like 'ラムラ — NGUYEN ANH HAO' or 'RAMURA - NGUYEN ANH HAO'."""
    match = EMPLOYEE_NAME_RE.search(line)
    if not match:
        return line.strip()
    before = line[:match.start()].strip(" \t-—–:：|")
    after = line[match.end():].strip(" \t-—–:：|")
    return before or after or line.strip()

def detect_employee_name(text):
    """Detect uppercase employee names from line 2 or inline report headers."""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if len(lines) >= 2:
        # Dong 2 phai la chu hoa
        candidate = lines[1].strip()
        if _is_employee_name(candidate):
            return candidate
    # Fallback: tim ten dai nhat
    matches = EMPLOYEE_NAME_RE.findall(text)
    if matches:
        return max(matches, key=lambda m: len(m.split()))
    return None

def detect_company_name(text):
    lines = text.strip().split("\n")
    for line in lines[:3]:
        line = line.strip()
        if not line:
            continue
        if _is_employee_name(line):
            continue
        candidate = _strip_employee_name_from_company_line(line)
        if not candidate:
            continue
        if re.search(r"[\u3041-\u3096\u30A1-\u30F6\u4E00-\u9FFF]", candidate):
            return candidate
        if not _is_employee_name(candidate) and len(candidate) > 3:
            return candidate
    return None
