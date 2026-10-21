"""Reads TAFE's Delivery Request PDF (DeliveryRequest_12030621_....pdf from TAFE Channel).

    Order No.   Part No.      Part Name          Type of Bin/Box  Request(Unit) ... Unit Size  Qty
    1210000691  2439A0390160  FRAME ASSY. ...    CARTON           1                 20         20

What the DQMS upload needs from it:
    Invoice Unit = invoice qty / Unit Size  (number of bins, as the DR counts them)
    Gap          = invoice qty differs from the DR qty -> the portal wants a Reason for Gap
The page is printed twice (office copy + "Vendor Copy"); only the first copy is read.
"""
import io
import re

DR_NO_RE = re.compile(r"Delivery\s+Request\s+No\.?\s*:\s*(\d{6,10})", re.I)
ROW_RE = re.compile(
    r"^\s*(\d{10})\s+([0-9A-Za-z][0-9A-Za-z.\-/]{4,20})\s+(.+?)\s{2,}(.+?)\s{2,}(\d+)\s+(?:.*?\s)?"
    r"(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*$")


def looks_like_dr(text):
    return "Delivery Request" in text and bool(DR_NO_RE.search(text))


def parse_text(text):
    """-> list of dict(dr_no, order_no, part, descr, bin, req, size, qty) for one DR."""
    first = re.split(r"Vendor\s+Copy", text, maxsplit=1)[0]
    m = DR_NO_RE.search(first) or DR_NO_RE.search(text)
    if not m:
        return []
    dr = m.group(1)
    rows = []
    for ln in first.splitlines():
        r = ROW_RE.match(ln)
        if r:
            rows.append(dict(dr_no=dr, order_no=r[1], part=r[2].upper(), descr=r[3].strip(), bin=r[4].strip(),
                             req=int(r[5]), size=float(r[6]), qty=float(r[7])))
    return rows


def parse_pdf(data):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    out, seen = [], set()
    for p in reader.pages:
        try:
            t = p.extract_text(extraction_mode="layout") or ""
        except Exception:  # noqa: BLE001
            t = p.extract_text() or ""
        for r in parse_text(t):
            k = (r["dr_no"], r["part"])
            if k not in seen:
                seen.add(k)
                out.append(r)
    return out


def first_page_text(data):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    try:
        return reader.pages[0].extract_text(extraction_mode="layout") or ""
    except Exception:  # noqa: BLE001
        return reader.pages[0].extract_text() or ""
