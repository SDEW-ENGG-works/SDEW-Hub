import urllib.parse

from ..http import ApiError, route
from ..services import builder, store
from ..services.defaults import load_settings


@route("POST", r"/api/upload")
def upload(req):
    name = urllib.parse.unquote(req.arg("name", "upload"))
    data = req._body_bytes
    if not data:
        raise ApiError("Empty file.")
    return store.ingest(name, data)


@route("GET", r"/api/bootstrap")
def bootstrap(req):
    return dict(settings=load_settings(), report=store.report_summary(), counts=store.counts())


@route("POST", r"/api/preview")
def preview(req):
    b = req.json
    return builder.build(b.get("selected"), b.get("edits") or {})


@route("POST", r"/api/generate")
def generate(req):
    b = req.json
    r = store.generate(b.get("selected") or [], b.get("edits") or {})
    from ...db import log
    log("dqms", "DQMS file made", f"{r['file_name']}: {r['summary'].get('invoices')} invoices")
    return r


@route("PUT", r"/api/invoices/edits")
def save_edits(req):
    b = req.json
    return store.save_edits(str(b.get("inv_no", "")), b.get("edits") or {})


@route("POST", r"/api/invoices/delete")
def delete_invoice(req):
    return store.remove_invoice(str(req.json.get("inv_no", "")))


# ---- "Get DQMS report" button: fetch it from TAFE Channel with Playwright (PC only) ----
@route("GET", r"/api/dqms/fetch")
def dqms_fetch_status(req):
    from ..services import dqms_portal
    return dict(dqms_portal.STATUS, available=dqms_portal.available(), why_not=dqms_portal.why_not())


@route("POST", r"/api/dqms/fetch")
def dqms_fetch_start(req):
    from ..services import dqms_portal
    problem = dqms_portal.why_not()
    if problem:
        raise ApiError(problem)
    if not dqms_portal.start(headed=bool(req.json.get("headed"))):
        raise ApiError("Already fetching - wait for it to finish.")
    return dict(dqms_portal.STATUS)
