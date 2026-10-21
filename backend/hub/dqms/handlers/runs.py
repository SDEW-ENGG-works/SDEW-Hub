import json
import re
import urllib.parse

from ..db import get_db, one, rows
from ..http import ApiError, Response, route


@route("GET", r"/api/runs")
def list_runs(req):
    out = rows("SELECT id, created_at, file_name, summary, invoices FROM dqms_runs ORDER BY id DESC LIMIT 300")
    for r in out:
        r["summary"] = json.loads(r["summary"] or "{}")
        r["invoices"] = json.loads(r["invoices"] or "[]")
    return out


@route("GET", r"/api/runs/(?P<id>\d+)/file")
def run_file(req):
    r = one("SELECT file_name, csv FROM dqms_runs WHERE id=?", (int(req.params["id"]),))
    if not r:
        raise ApiError("Not found", 404)
    fn = re.sub(r"[^A-Za-z0-9_\-]+", "_", re.sub(r"\.csv$", "", r["file_name"], flags=re.I)).strip("_.") + ".csv"
    return Response(bytes(r["csv"]), content_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f"attachment; filename=\"{fn}\"; filename*=UTF-8''{urllib.parse.quote(fn)}"})


@route("DELETE", r"/api/runs/(?P<id>\d+)")
def delete_run(req):
    rid = int(req.params["id"])
    con = get_db()
    con.execute("UPDATE invoices SET run_id=NULL WHERE run_id=?", (rid,))
    con.execute("DELETE FROM dqms_runs WHERE id=?", (rid,))
    con.commit()
    return dict(ok=True)
