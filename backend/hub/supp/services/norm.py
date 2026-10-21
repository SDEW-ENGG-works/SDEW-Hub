"""Small helpers shared by the parsers and the engine."""
import re
from datetime import date, datetime


def part_key(p):
    """'0190856M01 ' / '1868865MO2' / '1586A04901_NEW' -> comparable part number."""
    if p is None:
        return ""
    s = re.sub(r"[^0-9A-Z]", "", str(p).upper())
    return re.sub(r"(\d)MO(\d)", r"\1M0\2", s)


def text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def num(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return default


def to_iso(v):
    """Excel date / datetime / 'dd/mm/yyyy' / 'dd.mm.yyyy' -> 'yyyy-mm-dd' (or '')."""
    if v is None or v == "":
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y", "%d-%b-%y", "%d-%b-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def lead_number(s):
    m = re.match(r"\s*(\d+)", str(s or ""))
    return m.group(1) if m else ""


def fy_suffix(s):
    """'/26-27' for a properly written financial year suffix, else '' (typos like /26-29 give '')."""
    m = re.search(r"/(\d\d)-(\d\d)$", str(s or "").strip())
    if m and int(m.group(2)) == int(m.group(1)) + 1:
        return m.group(0)
    return ""
