"""TAFE Channel 'GRIN Details' export (.xls) -> grin_lines rows."""
from .norm import num, text, to_iso
from .readers import header_index, sheets

GRIN_HEAD = ["GRIN No", "GRIN Date", "Invoice Number"]


def looks_like_grin(first_row):
    return [str(v).strip() for v in first_row[:3]] == GRIN_HEAD


def parse(path):
    out = []
    for _, it in sheets(path):
        head = next(it, None)
        if not head or not looks_like_grin(head):
            continue
        ix = header_index(head)
        g = lambda r, k: r[ix[k]] if k in ix and ix[k] < len(r) else None
        for r in it:
            gno = text(g(r, "GRIN No"))
            if not gno:
                continue
            out.append(dict(
                grin_no=gno, line_no=text(g(r, "Line No")) or "1", grin_date=to_iso(g(r, "GRIN Date")),
                invoice_no=text(g(r, "Invoice Number")), invoice_date=to_iso(g(r, "Invoice Date")),
                plant=text(g(r, "Plant")), po_no=text(g(r, "PO No")), po_date=to_iso(g(r, "PO Date")),
                part_no=text(g(r, "Part No")), part_desc=text(g(r, "Part Desc")),
                grin_qty=num(g(r, "GRIN Qty"), 0), accepted_qty=num(g(r, "Accpt Qty"), 0),
                rejected_qty=num(g(r, "Rej Qty"), 0), part_rate=num(g(r, "Part Rate"), 0),
                freight=num(g(r, "Tot.Freight Rate"), 0)))
        break
    return out
