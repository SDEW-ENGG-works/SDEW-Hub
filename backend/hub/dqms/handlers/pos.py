from ..db import rows
from ..http import ApiError, route
from ..services import po


@route("GET", r"/api/pos")
def list_pos(req):
    heads = rows("SELECT po_no, plant, items, source, uploaded_at FROM po_headers ORDER BY plant, po_no")
    q = req.arg("q").strip().upper()
    items = []
    if q:
        items = rows("SELECT i.po_no, i.part, i.item, i.descr, i.rate, h.plant, o.item AS typed FROM po_items i "
                     "LEFT JOIN po_headers h ON h.po_no=i.po_no "
                     "LEFT JOIN line_overrides o ON o.po_no=i.po_no AND o.part=i.part "
                     "WHERE UPPER(i.part) LIKE ? OR i.po_no LIKE ? OR UPPER(i.descr) LIKE ? ORDER BY i.part, i.po_no LIMIT 300",
                     (f"%{q}%", f"%{q}%", f"%{q}%"))
    typed = rows("SELECT o.po_no, o.part, o.item, o.updated_at, i.item AS po_item FROM line_overrides o "
                 "LEFT JOIN po_items i ON i.po_no=o.po_no AND i.part=o.part ORDER BY o.updated_at DESC")
    return dict(pos=heads, items=items, typed=typed)


@route("POST", r"/api/pos/import-supp")
def import_supp(req):
    try:
        return po.import_supp_bill()
    except FileNotFoundError as e:
        raise ApiError(str(e), 404)


@route("PUT", r"/api/pos/line")
def set_line(req):
    b = req.json
    po_no, part = str(b.get("po_no", "")).strip(), str(b.get("part", "")).strip()
    item = b.get("item")
    if not po_no or not part:
        raise ApiError("Order No. and Part No. are needed")
    if item not in (None, "") and not str(item).strip().isdigit():
        raise ApiError("Line item must be a number")
    po.set_override(po_no, part, str(item).strip() if item not in (None, "") else None)
    return dict(ok=True)
