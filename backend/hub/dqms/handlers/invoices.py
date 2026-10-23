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
    return store.ingest(name, data, req.arg("batch", "") or None)


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


# ---- "Get DQMS report" button: TAFE Channel with plain web requests (no browser) - works on the PC and the website.
# If the website cannot reach TAFE Channel (it answers Indian addresses only), the SDEW PC does it (pc_jobs).
@route("GET", r"/api/dqms/fetch")
def dqms_fetch_status(req):
    from ... import config
    from ...services import pc_jobs
    from ..services import dqms_portal
    st = dict(dqms_portal.STATUS)
    if config.ON_VERCEL:
        j = pc_jobs.status("dqms_report")
        if j.get("running") or (j.get("started") or "") > (st.get("started") or ""):
            st = j
    return dict(st, available=dqms_portal.available(), why_not=dqms_portal.why_not())


@route("POST", r"/api/dqms/fetch")
def dqms_fetch_start(req):
    from ... import config
    from ...services import pc_jobs
    from ..services import dqms_portal
    problem = dqms_portal.why_not()
    if problem:
        raise ApiError(problem)
    dqms_portal.start()
    st = dict(dqms_portal.STATUS)
    if st["error"] and config.ON_VERCEL and dqms_portal.network_problem(st["error"]):
        a = pc_jobs.agent_info()
        if a and a["online"]:
            q = pc_jobs.queue("dqms_report", {})
            q["log"] = st["log"] + ["TAFE Channel did not answer this website - asking the SDEW PC instead"] + q["log"]
            return dict(q, queued=True, done=False)
    return dict(st, done=True)
