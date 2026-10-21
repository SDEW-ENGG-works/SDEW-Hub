"""Tally 'Sales Register' export (.xlsx/.xls) -> sales_lines rows.
The same workbook may also hold SDEW's own GRN sheet (INVOICE NO / PART NO / GRN NO / GRN DATE)."""
import re

from .norm import num, part_key, text, to_iso
from .readers import header_index, sheets

SALES_COLS = {"Voucher Number", "Party Name", "Item Name", "Billed Quantity", "Rate"}
GRN_COLS = {"INVOICE NO", "PART NO", "GRN NO", "GRN DATE"}


def _sales_rows(it, ix):
    g = lambda r, k: r[ix[k]] if k in ix and ix[k] < len(r) else None
    seqs, out = {}, []
    for r in it:
        v = text(g(r, "Voucher Number"))
        if not v:
            continue
        item = text(g(r, "Item Name"))
        part = part_key(g(r, "Item Part No")) or part_key(re.split(r"\s|-", item, 1)[0] if item else "")
        key = (v, part)
        seqs[key] = seqs.get(key, -1) + 1
        descr = item.split(" - ", 1)[1].strip() if " - " in item else text(g(r, "Item Description"))
        out.append(dict(voucher=v, part=part, seq=seqs[key], inv_date=to_iso(g(r, "Date")),
                        party=text(g(r, "Party Name")), order_no=text(g(r, "Order Number")),
                        order_due=to_iso(g(r, "Order Due Date")), item_name=item, descr=descr,
                        hsn=text(g(r, "Item HSN")), gst=num(g(r, "Item rate of GST"), 0),
                        qty=num(g(r, "Billed Quantity"), 0), rate=num(g(r, "Rate"), 0)))
    return out


def _grn_rows(it, ix):
    g = lambda r, k: r[ix[k]] if k in ix and ix[k] < len(r) else None
    seqs, out = {}, []
    for r in it:
        v = text(g(r, "INVOICE NO"))
        if not v:
            continue
        part = part_key(g(r, "PART NO"))
        key = (v, part)
        seqs[key] = seqs.get(key, -1) + 1
        out.append(dict(voucher=v, part=part, seq=seqs[key], grn_no=text(g(r, "GRN NO")),
                        grn_date=to_iso(g(r, "GRN DATE")), qty=num(g(r, "QTY"), 0)))
    return out


def parse(path):
    """-> (sales_rows, grn_rows, sheet names used). Uses the FIRST sales sheet and the FIRST GRN sheet."""
    sales, grn, used = None, None, []
    for name, it in sheets(path):
        head = next(it, None)
        if not head:
            continue
        ix = header_index(head)
        if sales is None and SALES_COLS <= set(ix):
            sales = _sales_rows(it, ix)
            used.append(name)
        elif grn is None and GRN_COLS <= set(ix):
            grn = _grn_rows(it, ix)
            used.append(name)
        if sales is not None and grn is not None:
            break
    return sales or [], grn or [], used


def looks_like_sales(path):
    for _, it in sheets(path):
        head = next(it, None)
        if head and (SALES_COLS <= set(header_index(head)) or GRN_COLS <= set(header_index(head))):
            return True
    return False
