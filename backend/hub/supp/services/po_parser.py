"""Reads a TAFE purchase order saved from TAFE Channel as .htm.

Both kinds of file look the same inside:
  1210000691.htm                                     (full PO, many pages)
  DS1615_1010016969_FinalPriceChange_03-10-2026.htm  (price-change copy)

Each item has date-wise price blocks:
    Valid from: 01.04.2026 to: 01.04.2026
    Gross Price            84.98 INR  1 PC
    Pkg.Charges   Qty       2.50 INR  1 PC
    Freight charges         1.80 INR  1 PC
A block's rate = Gross + Pkg.Charges + Freight.
"""
import re
from html.parser import HTMLParser

ITEM_RE = re.compile(r"^\s*(\d{1,4})\s+([0-9A-Z]{6,14})\s+-\s*(\S*)\s+-\s+(.*?)\s*([\d,]+\.\d{2})\s+(\d+)\s+([A-Z]{2,3})\s*([\d,.]*)\s*$")
VALID_RE = re.compile(r"Valid from:\s*(\d\d\.\d\d\.\d{4})\s+to:\s*(\d\d\.\d\d\.\d{4})")
COND_RE = re.compile(r"^\s*(Gross Price|Pkg\.Charges\s+Qty|Freight charges|[A-Za-z][A-Za-z .]+?)\s+(-?[\d,]+\.\d+)\s+INR\s+(\d+)\s+(\w+)")


class _Lines(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.cur = []
        self.lines = []

    def handle_starttag(self, tag, attrs):
        if tag == "nobr":
            self.depth += 1
            self.cur = []
        elif tag == "br" and not self.depth:
            pass

    def handle_endtag(self, tag):
        if tag == "nobr" and self.depth:
            self.depth -= 1
            self.lines.append("".join(self.cur))

    def handle_data(self, data):
        if self.depth:
            self.cur.append(data)


def text_lines(html):
    p = _Lines()
    p.feed(html)
    lines = p.lines
    if not lines:  # not the usual SAP print layout: fall back to the plain text
        lines = re.sub(r"<[^>]+>", "\n", html).splitlines()
    return [l.replace("\xa0", " ").rstrip() for l in lines]


def looks_like_po(html):
    import html as _h
    t = _h.unescape(html[:200000]).replace("\xa0", " ")
    return "Purchase order" in t and ("P.O.No" in t or "PO number" in t)


def parse(html, bill_to_words=()):
    """-> dict(po_no, po_date, valid_till, bill_to, plant_hint, items=[...], warnings=[...])"""
    lines = text_lines(html)
    joined = "\n".join(lines)
    po_no = (re.search(r"P\.O\.No\.\s*:\s*(\d+)", joined) or re.search(r"\b(\d{10})\s*/\s*\d\d\.\d\d\.\d{4}", joined))
    po_date = re.search(r"P\.O\.No\.[^\n]*\n[^\n]*Date\s*:\s*([\d.]+)", joined)
    valid = re.search(r"Valid Till\s*:\s*([\d.]+)", joined)
    bill = re.search(r"Bill to & Ship to:[^\n]*\n((?:.*\n){1,5})", joined)
    bill_to = " ".join(l.strip() for l in (bill.group(1).splitlines() if bill else []) if l.strip())
    plant_hint = ""
    for code, word in bill_to_words:
        if word and word.lower() in joined.lower():
            plant_hint = code
            break

    items, cur, blk, warnings = [], None, None, []
    for ln in lines:
        ln = re.sub(r"_{3,}", " ", ln)
        m = ITEM_RE.match(ln)
        if m:
            cur = dict(item=int(m[1]), part=m[2], iss=m[3], descr=m[4].strip(), rate=float(m[5].replace(",", "")),
                       per=int(m[6]), uom=m[7], blocks=[])
            items.append(cur)
            blk = None
            continue
        m = VALID_RE.search(ln)
        if m and cur is not None:
            blk = dict(frm=m[1], to=m[2], conds={})
            cur["blocks"].append(blk)
            continue
        m = COND_RE.match(ln)
        if m and cur is not None:
            if blk is None:  # price with no validity dates: valid always
                blk = dict(frm="01.01.1900", to="31.12.9999", conds={})
                cur["blocks"].append(blk)
            name = m[1].strip()
            key = "gross" if name == "Gross Price" else "freight" if name.startswith("Freight") else "pkg" if name.startswith("Pkg") else name
            blk["conds"][key] = round(blk["conds"].get(key, 0) + float(m[2].replace(",", "")), 4)
            continue
        if re.search(r"\d+\.\d\d\s+INR", ln):
            warnings.append(f"Line not read: {ln.strip()[:80]}")
    return dict(po_no=po_no.group(1) if po_no else "", po_date=po_date.group(1) if po_date else "",
                valid_till=valid.group(1) if valid else "", bill_to=bill_to, plant_hint=plant_hint,
                items=items, warnings=warnings)


def _d(s):
    d, m, y = s.split(".")
    return (int(y), int(m), int(d))


def price_on(blocks, iso_day):
    """Rate (gross + pkg + freight) valid on a day 'yyyy-mm-dd', or None."""
    y, m, d = (int(x) for x in iso_day.split("-"))
    day = (y, m, d)
    for b in blocks:
        if _d(b["frm"]) <= day <= _d(b["to"]):
            return round(sum(b["conds"].values()), 2)
    return None
