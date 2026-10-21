"""Small helpers: invoice number keys, dates, payment-voucher numbers."""
import re
from datetime import date, datetime

_INV = re.compile(r"^0*(\d+)\s*[/\-]\s*(\d{2})\s*[/\-]\s*(\d{2})$")


def inv_key(v):
    """'9552/26/27', ' 9552/26-27 ', '9552-26-27' -> '9552/26-27'. Anything else: trimmed upper text."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = re.sub(r"\s+", "", str(v)).upper()
    m = _INV.match(s)
    if m:
        return f"{int(m.group(1))}/{m.group(2)}-{m.group(3)}"
    return s


def voucher_key(v):
    """Payment voucher / mark cell -> plain digits text ('138031571'). Text marks stay as text."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def iso(v):
    """dd/mm/yyyy, dd.mm.yyyy, datetime -> 'yyyy-mm-dd' ('' when not a date)."""
    if v is None or v == "":
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    m = re.match(r"^(\d{1,2})[./\-](\d{1,2})[./\-](\d{4})", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    return s[:10] if m else ""


def dotted(iso_date):
    """'2026-10-16' -> '16.10.2026' (how the register's payment date column is written)."""
    if not iso_date or len(iso_date) < 10:
        return iso_date or ""
    return f"{iso_date[8:10]}.{iso_date[5:7]}.{iso_date[0:4]}"


def num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def edit_distance(a, b):
    """Levenshtein distance (used to spot a mistyped voucher number like 1383032039)."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]
