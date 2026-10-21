"""Reads SDEW's Tally tax invoice PDFs (e-Invoice print).

One PDF can hold one invoice or many (one after the other, or the same invoice printed
twice as Original / Duplicate). Each page is read on its own, pages are grouped by
invoice number, and a repeated copy of an invoice is taken once.

What is taken from each invoice:
    Invoice No.          13669/26-27
    Dated                13-Oct-26              -> 13.10.2026
    Buyer's Order No.    1210000691             -> Order No.
    item lines           1210A01402 - ASSY BREATHER PIPE LH ... 50.000 QTY  153.99  QTY  7,699.50
    Output IGST / CGST / SGST amounts
    Total                8,084.00               -> Final Invoice Value
    No of Packeges :1                           -> Invoice Unit
    Remarks: ... DR 12029209                    -> DR No.
"""
import io
import re
from datetime import datetime

INV_RE = re.compile(r"\b(\d{1,6}/\d{2}-\d{2})\b")
DATE_RE = re.compile(r"\b(\d{1,2}-[A-Za-z]{3}-\d{2,4})\b")
ITEM_RE = re.compile(
    r"^\s*(\d{1,3})\s+([0-9A-Za-z][0-9A-Za-z.\-/]{4,20}?)\s*-\s*(.+?)\s{2,}(\d{4,8})\s+.*?"
    r"([\d,]+\.\d{1,3})\s+([A-Za-z]{2,5})\s+([\d,]+\.\d{1,4})\s+[A-Za-z]{2,5}\s+([\d,]+\.\d{2})\s*$")
TAX_RE = re.compile(r"Output\s+(IGST|CGST|SGST|UTGST)\b[^\n]*?(-?[\d,]+\.\d{2})\s*$", re.M)
TOTAL_RE = re.compile(r"^\s*Total\s+.*?([\d,]+\.\d{2})\s*(?:₹|Rs\.?|INR)?\s*$", re.M)
ROUND_RE = re.compile(r"Round\s*Off\s+(\(-\))?\s*(-?[\d,]+\.\d{2})")
PKG_RE = re.compile(r"No\.?\s*of\s*Pack\w*\s*:\s*(\d+)", re.I)
DR_RE = re.compile(r"(?<![A-Za-z])D\.?D?\.?R\.?\s*(?:No\.?)?\s*[:.\-]?\s*(\d{6,10})\b", re.I)
EWAY_RE = re.compile(r"e\s*-?\s*Way\s*Bill\s*(?:No\.?|Number)?\s*[:.\-]?\s*(\d{4}\s?\d{4}\s?\d{4})", re.I)
ORDER_RE = re.compile(r"\b(1\d{9}|2\d{9})\b")


def _num(s):
    return float(str(s).replace(",", ""))


def _date(s):
    for fmt in ("%d-%b-%y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def page_texts(data):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    out = []
    for p in reader.pages:
        try:
            t = p.extract_text(extraction_mode="layout")
        except Exception:  # noqa: BLE001  (older pypdf: no layout mode)
            t = p.extract_text()
        out.append(t or "")
    return out


def parse_page(text):
    """-> dict for one invoice page, or None when the page has no invoice number."""
    lines = text.splitlines()
    inv_no = inv_date = None
    for i, ln in enumerate(lines):
        if "Invoice No" in ln:
            for nxt in lines[i:i + 4]:
                m = INV_RE.search(nxt)
                if m:
                    inv_no = m.group(1)
                    d = DATE_RE.search(nxt[m.end():])
                    if d:
                        inv_date = _date(d.group(1))
                    break
            break
    if not inv_no:
        m = INV_RE.search(text)
        if not m:
            return None
        inv_no = m.group(1)
    if not inv_date:
        after = text[text.find(inv_no):]
        d = DATE_RE.search(after)
        inv_date = _date(d.group(1)) if d else ""

    order_no = ""
    k = text.find("Buyer's Order No")
    if k < 0:
        k = text.find("Order No")
    if k >= 0:
        m = ORDER_RE.search(text[k:k + 1500])
        if m:
            order_no = m.group(1)

    items = []
    for ln in lines:
        m = ITEM_RE.match(ln)
        if m:
            items.append(dict(sl=int(m[1]), part=m[2].strip(" -").upper(), descr=m[3].strip(), hsn=m[4],
                              qty=_num(m[5]), uom=m[6], rate=_num(m[7]), amount=_num(m[8])))

    taxes = {}
    for m in TAX_RE.finditer(text):
        taxes[m[1].lower()] = round(taxes.get(m[1].lower(), 0) + _num(m[2]), 2)

    # grand total = the "Total   50.000 QTY   8,084.00 ₹" line (not the tax summary's "Total")
    total = None
    cut = text.find("Amount Chargeable")
    for m in TOTAL_RE.finditer(text):
        if "₹" in m.group(0) or "INR" in m.group(0) or "Rs" in m.group(0):
            total = _num(m.group(1))
            break
        if total is None and (cut < 0 or m.start() < cut):
            total = _num(m.group(1))
    rnd = ROUND_RE.search(text)
    round_off = (-1 if rnd and rnd.group(1) else 1) * _num(rnd.group(2)) if rnd else 0.0

    pk = PKG_RE.search(text)
    rem = text[text.find("Remarks"):] if "Remarks" in text else text
    drs = list(dict.fromkeys(DR_RE.findall(rem)))
    ew = EWAY_RE.search(text)
    return dict(eway=re.sub(r"\s", "", ew.group(1)) if ew else "", inv_no=inv_no, inv_date=inv_date, order_no=order_no, items=items, taxes=taxes,
                total=total, round_off=round_off, packages=int(pk.group(1)) if pk else None, drs=drs,
                consignee=_consignee(text))


def _consignee(text):
    k = text.find("Consignee")
    if k < 0:
        return ""
    chunk = text[k:k + 400].splitlines()[1:6]
    return " ".join(re.split(r"\s{3,}", c.strip())[0] for c in chunk if c.strip())[:200]


def parse_pdf(data):
    """-> (invoices, warnings). Pages of the same invoice are merged; a second copy is ignored."""
    invoices, order, warnings = {}, [], []
    cur = None
    for n, text in enumerate(page_texts(data), 1):
        p = parse_page(text)
        if not p:
            if text.strip() and cur:
                warnings.append(f"Page {n}: no invoice number - read as part of {cur}")
            continue
        no = p["inv_no"]
        if no not in invoices:
            invoices[no] = p
            order.append(no)
        else:
            inv = invoices[no]
            same = [(i["part"], i["qty"]) for i in inv["items"]] == [(i["part"], i["qty"]) for i in p["items"]]
            if not same and p["items"]:
                # a continuation page of a long invoice: add its lines and its totals
                known = {(i["sl"], i["part"]) for i in inv["items"]}
                inv["items"] += [i for i in p["items"] if (i["sl"], i["part"]) not in known]
                if p["total"] is not None:
                    inv["total"] = p["total"]
                for k, v in p["taxes"].items():
                    inv["taxes"][k] = v
                inv["drs"] = list(dict.fromkeys(inv["drs"] + p["drs"]))
                if p["packages"] is not None:
                    inv["packages"] = p["packages"]
        cur = no
    out = []
    for no in order:
        inv = invoices[no]
        w = []
        if not inv["items"]:
            w.append("No item line found")
        if not inv["order_no"]:
            w.append("Buyer's Order No. not found")
        if not inv["drs"]:
            w.append("No DR number in Remarks")
        elif len(inv["drs"]) > 1:
            w.append(f"More than one DR in Remarks: {', '.join(inv['drs'])}")
        if inv["total"] is None:
            w.append("Invoice total not found")
        else:
            calc = sum(i["amount"] for i in inv["items"]) + sum(inv["taxes"].values()) + inv["round_off"]
            if inv["items"] and abs(calc - inv["total"]) > 1.0:
                w.append(f"Lines + tax ({calc:,.2f}) do not add up to the total ({inv['total']:,.2f})")
        if inv["packages"] is None:
            w.append("'No of Packeges' not found - Invoice Unit left blank")
        inv["warnings"] = w
        out.append(inv)
    return out, warnings
