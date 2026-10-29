import json
import urllib.parse

from ..db import get_setting, one, rows
from .. import route
from ...http import ApiError, Response
from ..services.engine import cleared_at, latest_run_id, run_summary
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


@route("POST", r"/api/refresh")
def refresh(req):
    """Refresh button: the Payment marking page starts empty again (register, payment exports and result).
    Nothing is deleted; uploads after this are a new start."""
    from datetime import datetime
    from ..db import set_setting
    set_setting("cleared_at", datetime.now().isoformat(timespec="microseconds"))
    set_setting("register_file", None)
    return dict(ok=True)


@route("GET", r"/api/bootstrap")
def bootstrap(req):
    fid = get_setting("register_file")
    reg = one("SELECT id, name, uploaded_at, rows, info FROM pm_files WHERE id=?", (fid,)) if fid else None
    if reg:
        reg["info"] = json.loads(reg["info"] or "{}")
    pay = one("SELECT COUNT(*) n, COUNT(DISTINCT pv) vouchers, MIN(pv_date) first, MAX(pv_date) last FROM pm_pay_lines "
              "WHERE loaded_at >= ?", (cleared_at(),))
    vouchers = rows("SELECT v.pv, v.pv_date, v.amount, COUNT(p.pv) lines FROM pm_vouchers v "
                    "LEFT JOIN pm_pay_lines p ON p.pv=v.pv GROUP BY v.pv ORDER BY v.pv_date DESC, v.pv DESC")
    rid = latest_run_id()
    return dict(register=reg, payments=pay, vouchers=vouchers, run=run_summary(rid) if rid else None,
                settings=load_settings())


@route("GET", r"/api/files/(?P<fid>\d+)/download")
def download_file(req):
    """Any uploaded file back as it was uploaded - the earlier versions of the register / sales file."""
    import os as _os
    import urllib.parse as _up
    from ..services.ingest import file_path
    f = one("SELECT name FROM pm_files WHERE id=?", (int(req.params["fid"]),))
    path = file_path(int(req.params["fid"])) if f else None
    if not path or not _os.path.exists(path):
        raise ApiError("This file is no longer stored.", 404)
    with open(path, "rb") as fh:
        data = fh.read()
    ctype = "application/vnd.ms-excel" if f["name"].lower().endswith(".xls") else \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(data, 200, ctype, {"Content-Disposition": f"attachment; filename=\"{f['name']}\"; "
                                       f"filename*=UTF-8''{_up.quote(f['name'])}"})
