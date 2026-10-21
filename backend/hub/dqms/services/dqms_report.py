"""Reads TAFE's "DQMS Batch Details Report" (.xls downloaded from TAFE Channel).

    Part Number | Part Description | Batch Number | Total Batch Quantity |
    Batch Consumed Quantity | Batch Balance Quantity | Creation Time (dd/mm/yyyy hh:mm:ss)
"""
import io
import re
from datetime import datetime

HEAD = {
    "part": ("part number", "part no"),
    "descr": ("part description",),
    "batch": ("batch number", "batch no"),
    "total": ("total batch quantity",),
    "consumed": ("batch consumed quantity",),
    "balance": ("batch balance quantity",),
    "created": ("creation time",),
}


def looks_like_report(rows):
    text = " ".join(str(c) for r in rows[:6] for c in r).lower()
    return "batch number" in text and "batch balance" in text


def read_rows(name, data):
    if name.lower().endswith((".xlsx", ".xlsm")) or data[:2] == b"PK":
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        ws = wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    import xlrd
    book = xlrd.open_workbook(file_contents=data)
    sh = book.sheet_by_index(0)
    return [sh.row_values(i) for i in range(sh.nrows)]


def _num(v):
    if v in (None, ""):
        return 0.0
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return 0.0


def _when(v):
    s = str(v or "").strip()
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%d-%m-%Y %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return s


def _part(v):
    s = str(v or "").strip()
    return s[:-2] if re.fullmatch(r"\d+\.0", s) else s


def parse(rows):
    """-> dict(report_time, batches=[...]). report_time comes from the file name when present."""
    hdr_i, cols = None, {}
    for i, r in enumerate(rows[:15]):
        low = [str(c or "").strip().lower() for c in r]
        if any(c in HEAD["batch"] for c in low):
            hdr_i = i
            for key, names in HEAD.items():
                for j, c in enumerate(low):
                    if c in names:
                        cols[key] = j
                        break
            break
    if hdr_i is None or "batch" not in cols or "part" not in cols:
        raise ValueError("No 'Part Number' / 'Batch Number' header in this file.")
    out = []
    for r in rows[hdr_i + 1:]:
        g = lambda k: r[cols[k]] if k in cols and cols[k] < len(r) else None  # noqa: E731
        batch = str(g("batch") or "").strip()
        part = _part(g("part"))
        if not batch or not part:
            continue
        out.append(dict(batch_no=batch, part=part, descr=str(g("descr") or "").strip(),
                        total=_num(g("total")), consumed=_num(g("consumed")), balance=_num(g("balance")),
                        created=_when(g("created"))))
    return out


def time_from_name(name):
    """DQMSBatchDetailsReport13102026163000.xls -> 2026-10-13 16:30:00"""
    m = re.search(r"(\d{2})(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})", name or "")
    if not m:
        return ""
    d, mo, y, h, mi, s = m.groups()
    try:
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s)).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ""
