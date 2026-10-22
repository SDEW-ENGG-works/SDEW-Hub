import urllib.parse

from ..db import get_db, rows, one
from .. import route
from ...http import ApiError, Response
from ..services.engine import CATS, latest_run_id, run_check, run_summary
from ..services.export import check_report, marked_register

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _rid(req):
    rid = req.arg("run") or latest_run_id()
    if not rid:
        raise ApiError("Run the check first.")
    return int(rid)


@route("POST", r"/api/check")
def check(req):
    return run_check()


@route("GET", r"/api/check/lines")
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
        where.append("(inv LIKE ? OR pv LIKE ? OR reg_party LIKE ? OR note LIKE ? OR reg_mark LIKE ?)")
        args += [f"%{q}%"] * 5
    w = " AND ".join(where)
    limit, offset = int(req.arg("limit", "200")), int(req.arg("offset", "0"))
    total = one(f"SELECT COUNT(*) n FROM pm_run_lines WHERE {w}", args)["n"]
    data = rows(f"SELECT * FROM pm_run_lines WHERE {w} ORDER BY seq LIMIT ? OFFSET ?", args + [limit, offset])
    return dict(total=total, lines=data, run=rid)


@route("PUT", r"/api/check/lines/(?P<seq>\d+)")
def set_action(req):
    rid = _rid(req)
    action = req.json.get("action")
    if action not in ("mark", "skip"):
        raise ApiError("action must be mark or skip")
    l = one("SELECT cat, reg_row FROM pm_run_lines WHERE run_id=? AND seq=?", (rid, int(req.params["seq"])))
    if not l:
        raise ApiError("Line not found", 404)
    if action == "mark" and not l["reg_row"]:
        raise ApiError("This invoice is not in the register, so there is no row to mark.")
    if action == "mark" and l["cat"] == "Debit note only":
        raise ApiError("A debit note alone is not a payment — nothing to mark.")
    con = get_db()
    con.execute("UPDATE pm_run_lines SET action=? WHERE run_id=? AND seq=?", (action, rid, int(req.params["seq"])))
    con.commit()
    return run_summary(rid)


@route("PUT", r"/api/check/category")
def set_category(req):
    rid = _rid(req)
    body = req.json
    cat, action = body.get("cat"), body.get("action")
    if cat not in CATS or action not in ("mark", "skip"):
        raise ApiError("Bad category or action")
    if action == "mark" and cat in ("Debit note only", "Not in register", "Already marked"):
        raise ApiError(f"'{cat}' lines cannot be marked.")
    con = get_db()
    con.execute("UPDATE pm_run_lines SET action=? WHERE run_id=? AND cat=? AND reg_row IS NOT NULL", (action, rid, cat))
    con.commit()
    return run_summary(rid)


def _download(data, name):
    return Response(data, 200, XLSX, {"Content-Disposition": f"attachment; filename=\"{name}\"; "
                                      f"filename*=UTF-8''{urllib.parse.quote(name)}"})


@route("GET", r"/api/export/marked")
def export_marked(req):
    data, name, n = marked_register(_rid(req))
    return _download(data, name)


@route("GET", r"/api/export/report")
def export_report(req):
    data, name = check_report(_rid(req))
    return _download(data, name)
