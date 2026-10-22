"""Sales marking: GRN NO / DATE / QTY in the TAFE SALES DETAILS file. Fetch GRIN = the Supp Bill's /api/supp/grin/sync."""
import json
import urllib.parse

from .. import route
from ..db import get_db, get_setting, one, rows
from ...http import ApiError, Response
from ..services.sales import CATS, LOCKED, latest_sales_run, marked_sales, run_sales, sales_report, sales_summary

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _rid(req):
    rid = req.arg("run") or latest_sales_run()
    if not rid:
        raise ApiError("Run the sales check first.")
    return int(rid)


@route("GET", r"/api/sales/bootstrap")
def bootstrap(req):
    fid = get_setting("sales_file")
    f = one("SELECT id, name, uploaded_at, rows, info FROM pm_files WHERE id=?", (fid,)) if fid else None
    if f:
        f["info"] = json.loads(f["info"] or "{}")
    g = one("SELECT COUNT(*) n, COUNT(DISTINCT grin_no) grins, MIN(grin_date) first, MAX(grin_date) last, "
            "MAX(updated_at) updated FROM grin_lines")
    rid = latest_sales_run()
    return dict(file=f, grin=g, run=sales_summary(rid) if rid else None)


@route("POST", r"/api/sales/check")
def check(req):
    return run_sales()


@route("GET", r"/api/sales/lines")
def lines(req):
    rid = _rid(req)
    where, args = ["run_id=?"], [rid]
    cat = req.arg("cat")
    if cat == "marking":
        where.append("action='mark'")
    elif cat:
        where.append("cat=?")
        args.append(cat)
    q = req.arg("q").strip()
    if q:
        where.append("(inv LIKE ? OR part LIKE ? OR grin_no LIKE ? OR sheet_gno LIKE ? OR party LIKE ? OR note LIKE ?)")
        args += [f"%{q}%"] * 6
    w = " AND ".join(where)
    limit, offset = int(req.arg("limit", "200")), int(req.arg("offset", "0"))
    total = one(f"SELECT COUNT(*) n FROM ps_lines WHERE {w}", args)["n"]
    data = rows(f"SELECT * FROM ps_lines WHERE {w} ORDER BY seq LIMIT ? OFFSET ?", args + [limit, offset])
    return dict(total=total, lines=data, run=rid)


@route("PUT", r"/api/sales/lines/(?P<seq>\d+)")
def set_action(req):
    rid = _rid(req)
    action = req.json.get("action")
    if action not in ("mark", "skip"):
        raise ApiError("action must be mark or skip")
    l = one("SELECT cat, grin_no FROM ps_lines WHERE run_id=? AND seq=?", (rid, int(req.params["seq"])))
    if not l:
        raise ApiError("Line not found", 404)
    if action == "mark" and (l["cat"] in LOCKED or not l["grin_no"]):
        raise ApiError("Nothing from TAFE GRIN to write on this line.")
    con = get_db()
    con.execute("UPDATE ps_lines SET action=? WHERE run_id=? AND seq=?", (action, rid, int(req.params["seq"])))
    con.commit()
    return sales_summary(rid)


@route("PUT", r"/api/sales/category")
def set_category(req):
    rid = _rid(req)
    cat, action = req.json.get("cat"), req.json.get("action")
    if cat not in CATS or action not in ("mark", "skip"):
        raise ApiError("Bad category or action")
    if action == "mark" and cat in LOCKED:
        raise ApiError(f"'{cat}' lines cannot be written.")
    con = get_db()
    con.execute("UPDATE ps_lines SET action=? WHERE run_id=? AND cat=? AND grin_no<>''", (action, rid, cat))
    con.commit()
    return sales_summary(rid)


def _download(data, name):
    return Response(data, 200, XLSX, {"Content-Disposition": f"attachment; filename=\"{name}\"; "
                                      f"filename*=UTF-8''{urllib.parse.quote(name)}"})


@route("GET", r"/api/sales/export/marked")
def export_marked(req):
    data, name, n = marked_sales(_rid(req))
    return _download(data, name)


@route("GET", r"/api/sales/export/report")
def export_report(req):
    data, name = sales_report(_rid(req))
    return _download(data, name)
