import json
import urllib.parse

from ..db import get_db, one, rows
from ..http import ApiError, Response, route

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _ctype(fname):
    return "application/zip" if fname.lower().endswith(".zip") else XLSX


@route("GET", r"/api/runs")
def list_runs(req):
    out = rows("SELECT id, batch_id, created_at, file_name, doc_date, summary, leap_status, leap_at, "
               "leap_result FROM chep_runs ORDER BY id DESC LIMIT 300")
    for r in out:
        r["summary"] = json.loads(r["summary"] or "{}")
        res = json.loads(r.pop("leap_result") or "{}")
        r["leap"] = {k: res.get(k) for k in ("confirmed", "missing", "short", "extra", "invoices", "retry_run_id", "error")}
    return out


@route("GET", r"/api/runs/(?P<id>\d+)")
def get_run(req):
    r = one("SELECT id, created_at, file_name, doc_date, summary, rows FROM chep_runs WHERE id=?", (int(req.params["id"]),))
    if not r:
        raise ApiError("Not found", 404)
    r["summary"] = json.loads(r["summary"] or "{}")
    r["rows"] = json.loads(r["rows"] or "[]")
    return r


@route("GET", r"/api/runs/(?P<id>\d+)/excel")
def run_excel(req):
    r = one("SELECT file_name, xlsx FROM chep_runs WHERE id=?", (int(req.params["id"]),))
    if not r:
        raise ApiError("Not found", 404)
    fn = r["file_name"]
    return Response(bytes(r["xlsx"]), content_type=_ctype(fn), headers={
        "Content-Disposition": f"attachment; filename=\"{fn}\"; filename*=UTF-8''{urllib.parse.quote(fn)}"})


@route("DELETE", r"/api/runs/(?P<id>\d+)")
def delete_run(req):
    con = get_db()
    con.execute("DELETE FROM chep_runs WHERE id=?", (int(req.params["id"]),))
    con.commit()
    return dict(ok=True)


@route("POST", r"/api/runs/combine")
def combine_runs(req):
    from ..services.store import combine
    fname, xlsx, note = combine(req.json.get("ids"))
    return Response(xlsx, content_type=_ctype(fname), headers={
        "Content-Disposition": f"attachment; filename=\"{fname}\"; filename*=UTF-8''{urllib.parse.quote(fname)}",
        "X-Combine-Note": urllib.parse.quote(note)})
