import json

from ..db import one, rows
from ..http import ApiError, Response, route
from ..services import engine, export
from ..services.defaults import load_settings


@route("POST", r"/api/bill/run")
def run(req):
    if not one("SELECT 1 x FROM sales_lines LIMIT 1"):
        raise ApiError("Upload the Tally Sales Register first.")
    if not one("SELECT 1 x FROM po_items LIMIT 1"):
        raise ApiError("Upload at least one PO first.")
    r = engine.run()
    from ...db import log
    t = r["summary"]["total"]
    log("supp", "bill calculated", f"{t['bill_lines']} lines, basic Rs {t['bill_value']:,.2f}")
    return r


def _run_id(req):
    rid = req.arg("run") or engine.latest_run_id()
    if not rid:
        raise ApiError("No bill yet - press Calculate bill.", 404)
    return int(rid)


@route("GET", r"/api/bill/lines")
def lines(req):
    rid = _run_id(req)
    where, args = ["run_id=?"], [rid]
    if req.arg("plant"):
        where.append("plant=?")
        args.append(req.arg("plant"))
    cat = req.arg("cat", "Bill")
    if cat == "not-bill":
        where.append("cat<>'Bill'")
    elif cat:
        where.append("cat=?")
        args.append(cat)
    if req.arg("q"):
        q = f"%{req.arg('q').strip()}%"
        where.append("(voucher LIKE ? OR part LIKE ? OR descr LIKE ? OR grn_no LIKE ? OR po_no LIKE ? OR reason LIKE ?)")
        args += [q] * 6
    w = " AND ".join(where)
    total = one(f"SELECT COUNT(*) n, ROUND(SUM(value),2) v, SUM(qty) q FROM run_lines WHERE {w}", args)
    limit = min(int(req.arg("limit", "200") or 200), 1000)
    offset = int(req.arg("offset", "0") or 0)
    data = rows(f"SELECT * FROM run_lines WHERE {w} ORDER BY plant, part, inv_date, voucher LIMIT ? OFFSET ?",
                args + [limit, offset])
    reasons = rows(f"SELECT cat, reason, COUNT(*) n, ROUND(SUM(value),2) v FROM run_lines WHERE {w} "
                   "GROUP BY cat, reason ORDER BY n DESC LIMIT 300", args) if cat != "Bill" else []
    return dict(total=total["n"], value=total["v"] or 0, qty=total["q"] or 0, lines=data, reasons=reasons)


@route("GET", r"/api/bill/runs")
def runs(req):
    out = rows("SELECT id, created_at, summary FROM bill_runs ORDER BY id DESC LIMIT 20")
    for r in out:
        r["summary"] = json.loads(r["summary"])["total"]
    return out


@route("GET", r"/api/bill/export")
def export_xlsx(req):
    rid = _run_id(req)
    run = one("SELECT params, created_at FROM bill_runs WHERE id=?", (rid,))
    params = json.loads(run["params"])
    body = export.build(rid, params.get("diff_basis", "po"))
    name = f"SDEW_Supplementary_Bill_{run['created_at'][:10]}.xlsx"
    return Response(body, 200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    {"Content-Disposition": f'attachment; filename="{name}"'})


@route("GET", r"/api/bill/export-pending")
def export_pending_xlsx(req):
    rid = _run_id(req)
    run = one("SELECT created_at FROM bill_runs WHERE id=?", (rid,))
    body = export.build_pending(rid)
    name = f"SDEW_GRIN_Pending_List_{run['created_at'][:10]}.xlsx"
    return Response(body, 200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    {"Content-Disposition": f'attachment; filename="{name}"'})
