import json
import urllib.parse

from ..db import get_setting, one, rows
from .. import route
from ...http import ApiError
from ..services.engine import latest_run_id, run_summary
from ..services.defaults import load_settings
from ..services.ingest import ingest


@route("POST", r"/api/upload")
def upload(req):
    name = urllib.parse.unquote(req.arg("name", "upload"))
    data = req._body_bytes
    if not data:
        raise ApiError("Empty file.")
    return ingest(name, data)


@route("GET", r"/api/files")
def list_files(req):
    out = rows("SELECT id, kind, name, uploaded_at, rows, info FROM pm_files ORDER BY id DESC LIMIT 300")
    for r in out:
        r["info"] = json.loads(r["info"] or "{}")
    return out


@route("GET", r"/api/bootstrap")
def bootstrap(req):
    fid = get_setting("register_file")
    reg = one("SELECT id, name, uploaded_at, rows, info FROM pm_files WHERE id=?", (fid,)) if fid else None
    if reg:
        reg["info"] = json.loads(reg["info"] or "{}")
    pay = one("SELECT COUNT(*) n, COUNT(DISTINCT pv) vouchers, MIN(pv_date) first, MAX(pv_date) last FROM pm_pay_lines")
    vouchers = rows("SELECT v.pv, v.pv_date, v.amount, COUNT(p.pv) lines FROM pm_vouchers v "
                    "LEFT JOIN pm_pay_lines p ON p.pv=v.pv GROUP BY v.pv ORDER BY v.pv_date DESC, v.pv DESC")
    rid = latest_run_id()
    return dict(register=reg, payments=pay, vouchers=vouchers, run=run_summary(rid) if rid else None,
                settings=load_settings())
