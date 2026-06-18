import re

def detect_employee_name(text):
    """Tên ứng viên luôn ở dòng 2 (sau tên công ty)."""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if len(lines) >= 2:
        # Dong 2 phai la chu hoa
        candidate = lines[1].strip()
        if re.match(r"^[A-Z\s]+$", candidate) and len(candidate) > 3:
            return candidate
    # Fallback: tim ten dai nhat
    pattern = r"\b([A-Z]{2,}(?:\s+[A-Z]{2,}){1,4})\b"
    matches = re.findall(pattern, text)
    if matches:
        return max(matches, key=lambda m: len(m.split()))
    return None

def detect_company_name(text):
    lines = text.strip().split("\n")
    for line in lines[:3]:
        line = line.strip()
        if not line:
            continue
        if re.search(r"[\u3041-\u3096\u30A1-\u30F6\u4E00-\u9FFF]", line):
            return line
        if not re.match(r"^[A-Z\s]+$", line) and len(line) > 3:
            return line
    return None
