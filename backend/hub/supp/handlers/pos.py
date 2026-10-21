import json

from ..db import get_db, one, rows
from ..http import ApiError, route
from ..services.defaults import load_settings
from ..services.po_parser import price_on


@route("GET", r"/api/pos")
def list_pos(req):
    s = load_settings()
    out = rows("SELECT * FROM po_headers ORDER BY plant, po_no")
    used = {r["po_no"]: r["n"] for r in rows(
        "SELECT po_no, COUNT(*) n FROM run_lines WHERE run_id=(SELECT MAX(id) FROM bill_runs) AND cat='Bill' GROUP BY po_no")}
    for h in out:
        items = rows("SELECT blocks FROM po_items WHERE po_no=?", (h["po_no"],))
        rev = 0
        for it in items:
            b = json.loads(it["blocks"])
            o, n = price_on(b, s["old_date"]), price_on(b, s["new_date"])
            if o is not None and n is not None and round(n - o, 2) != 0:
                rev += 1
        h["revised"] = rev
        h["bill_lines"] = used.get(h["po_no"], 0)
    return out


@route("GET", r"/api/pos/(?P<po>\d+)")
def po_items(req):
    s = load_settings()
    h = one("SELECT * FROM po_headers WHERE po_no=?", (req.params["po"],))
    if not h:
        raise ApiError("PO not found", 404)
    ovr = {o["part"]: o["revised"] for o in s["overrides"]}
    items = rows("SELECT * FROM po_items WHERE po_no=? ORDER BY item", (req.params["po"],))
    for it in items:
        b = json.loads(it.pop("blocks"))
        it["old"], it["new"] = price_on(b, s["old_date"]), price_on(b, s["new_date"])
        if it["part"] in ovr and it["old"] is not None:
            it["new"], it["override"] = ovr[it["part"]], True
        it["blocks"] = b
    h["items"] = items
    return h


@route("PUT", r"/api/pos/(?P<po>\d+)")
def set_plant(req):
    plant = (req.json.get("plant") or "").strip()
    con = get_db()
    con.execute("UPDATE po_headers SET plant=? WHERE po_no=?", (plant, req.params["po"]))
    con.commit()
    return dict(ok=True)


@route("DELETE", r"/api/pos/(?P<po>\d+)")
def delete_po(req):
    con = get_db()
    con.execute("DELETE FROM po_items WHERE po_no=?", (req.params["po"],))
    con.execute("DELETE FROM po_headers WHERE po_no=?", (req.params["po"],))
    con.commit()
    return dict(ok=True)
