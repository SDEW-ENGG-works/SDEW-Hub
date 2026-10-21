"""Reads SDEW's packing list workbook (one sheet per plant / transporter / day).

Each packing-list sheet looks like:
    SRI DURGA ENGINEERING WORKS
    MDU - UDDHAVA TRANSPORTS   -  05-10-2026
    PACKING LIST
    S NO | DR NO | PART NAME | Total Qty | Invoice No | Date | CHEP | CARTON | 0 | 1 | 2 | 3 | 8
    1    | 12015994 | 1310A09701 - ASSY BREATHER PIPE RH | 20 | 13048/26-27 | 05-10-26 | 2 |  |  |  |  | 2 |
    ...
    (totals row)

The columns after CARTON are the CHEP sizes (0/1/2/3/8 or 14400..14403); the number in
them is how many CHEPs of that size go with the invoice. Sheets without that header
(pivot sheets etc.) are ignored.
"""
import re
from datetime import date, datetime, timedelta

from .defaults import type_lookup
from .readers import sheets

_DATE = re.compile(r"(\d{1,2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{2,4})")
_PART = re.compile(r"^\s*([0-9A-Za-z]{6,})")


def part_key(name):
    m = _PART.match(str(name or ""))
    return m.group(1).upper() if m else ""


def _txt(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _num(v):
    if v in (None, ""):
        return 0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0


def _to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and 30000 < v < 80000:
        return date(1899, 12, 30) + timedelta(days=int(v))
    if isinstance(v, str):
        return _date_in_text(v)
    return None


def _date_in_text(s):
    m = _DATE.search(s or "")
    if not m:
        return None
    d, mth, y = (int(x) for x in m.groups())
    if y < 100:
        y += 2000
    try:
        return date(y, mth, d)
    except ValueError:
        return None


def _find_header(rows):
    for i, r in enumerate(rows[:20]):
        up = [_txt(v).upper() for v in r]
        if any("CHEP" in u for u in up) and any("INVOICE" in u for u in up):
            return i
    return None


def _columns(header):
    up = [_txt(v).upper() for v in header]
    col = {}

    def first(pred):
        for i, u in enumerate(up):
            if u and pred(u):
                return i
        return None

    col["sno"] = first(lambda u: u in ("S NO", "SN", "SL.N", "SL NO", "S.NO", "SNO") or u.startswith("SL"))
    col["dr"] = first(lambda u: u in ("DR", "DR NO", "DR.NO"))
    col["part"] = first(lambda u: "PART" in u or "MATERIAL" in u or "DESC" in u)
    col["qty"] = first(lambda u: "QTY" in u)
    col["invoice"] = first(lambda u: "INVOICE" in u and "DATE" not in u and "AMOUNT" not in u)
    col["date"] = first(lambda u: "DATE" in u)
    col["chep"] = first(lambda u: "CHEP" in u)
    col["carton"] = first(lambda u: "CARTON" in u or u == "CT BOX")
    start = max(c for c in (col["chep"], col["carton"]) if c is not None) + 1
    col["sizes"] = [(i, up[i]) for i in range(start, len(up)) if up[i]]
    return col


def parse_packing_list(path, settings):
    """Returns {sheets: [...], skipped: [...]} with every packing-list line."""
    lookup = type_lookup(settings)
    plant_codes = [p["code"].upper() for p in settings["plants"] if p.get("code")]
    out, skipped = [], []
    for sheet_name, it in sheets(path):
        rows = list(it)
        h = _find_header(rows)
        if h is None:
            skipped.append(sheet_name)
            continue
        col = _columns(rows[h])
        if col["invoice"] is None or col["part"] is None or col["chep"] is None:
            skipped.append(sheet_name)
            continue
        title_lines = [" ".join(_txt(v) for v in r if _txt(v)) for r in rows[:h]]
        title_lines = [t for t in title_lines if t]
        title = " · ".join(t for t in title_lines if "SRI DURGA" not in t.upper() and t.upper() != "PACKING LIST")

        plant = ""
        for text in (title, sheet_name):
            for code in plant_codes:
                if re.search(rf"(^|[^A-Z]){re.escape(code)}([^A-Z]|$)", text.upper()):
                    plant = code
                    break
            if plant:
                break

        unknown_sizes = {}
        lines, inv_dates = [], {}
        for ri in range(h + 1, len(rows)):
            r = rows[ri]
            g = lambda c: r[c] if c is not None and c < len(r) else None  # noqa: E731
            inv, pname = _txt(g(col["invoice"])), _txt(g(col["part"]))
            if not inv or not pname or "CHEP" in " ".join(_txt(v).upper() for v in r):
                continue
            idate = _to_date(g(col["date"]))
            if idate:
                inv_dates[idate] = inv_dates.get(idate, 0) + 1
            sizes = {}
            for ci, token in col["sizes"]:
                n = _num(g(ci))
                if n <= 0:
                    continue
                code = lookup.get(token)
                if code is None:
                    unknown_sizes[token] = unknown_sizes.get(token, 0) + 1
                    code = f"?{token}"
                sizes[code] = sizes.get(code, 0) + int(round(n))
            lines.append(dict(
                key=f"{sheet_name}|{ri}", row=ri + 1, sno=_txt(g(col["sno"])), dr=_txt(g(col["dr"])),
                part_name=pname, part=part_key(pname), qty=_num(g(col["qty"])), invoice=inv,
                inv_date=idate.isoformat() if idate else None,
                chep=int(round(_num(g(col["chep"])))), carton=int(round(_num(g(col["carton"])))),
                sizes=sizes))
        if not lines:
            skipped.append(sheet_name)
            continue
        sheet_date = _date_in_text(" ".join(title_lines))
        if not sheet_date and inv_dates:
            sheet_date = max(inv_dates, key=inv_dates.get)
        out.append(dict(name=sheet_name, title=title, plant=plant,
                        date=sheet_date.isoformat() if sheet_date else None,
                        size_columns=[t for _, t in col["sizes"]], unknown_sizes=unknown_sizes,
                        lines=lines))

    # Tick the sheets of the latest dispatch day by default.
    dated = [s["date"] for s in out if s["date"] and s["plant"]]
    latest = max(dated) if dated else None
    for s in out:
        s["selected"] = bool(latest and s["date"] == latest and s["plant"])
    return dict(sheets=out, skipped=skipped, latest=latest)
