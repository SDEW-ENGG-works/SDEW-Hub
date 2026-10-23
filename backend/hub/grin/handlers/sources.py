import urllib.parse
from datetime import date, timedelta

from .. import route
from ..db import rows
from ...http import ApiError
from ..services import status as st
from ..services import status as st_
from ... import config
from ...services import pc_jobs
from ..services import tally
from ..services.defaults import load_settings, plants
from ..services.ingest import ingest
from ..services.mailer import smtp_settings


@route("POST", r"/api/upload")
def upload(req):
    name = urllib.parse.unquote(req.arg("name", "upload"))
    if not req._body_bytes:
        raise ApiError("Empty file.")
    return ingest(name, req._body_bytes)


def _one(sql, args=()):
    r = rows(sql, args)
    return r[0] if r else {}


@route("GET", r"/api/sources")
def sources(req):
    from ...supp.services import grin_portal
    s = load_settings()
    parties = [p["party"] for p in plants()]
    ph = ",".join("?" * len(parties)) or "''"
    return dict(
        tally=dict(url=s["tally_url"], companies=s["tally_companies"],
                   **_one("SELECT COUNT(*) n, MIN(inv_date) first, MAX(inv_date) last, MAX(pulled_at) pulled "
                          "FROM gp_tally_invoices"),
                   status=tally.STATUS if not config.ON_VERCEL else dict(running=False, log=[], error="", finished=""),
                   on_pc=config.ON_VERCEL, agent=pc_jobs.agent_info()),
        sales=_one(f"SELECT COUNT(DISTINCT voucher) n, MIN(inv_date) first, MAX(inv_date) last FROM sales_lines "
                   f"WHERE party IN ({ph})", parties),
        grin=dict(**_one("SELECT COUNT(DISTINCT grin_no) n, COUNT(DISTINCT invoice_no) invoices, MIN(grin_date) first, "
                         "MAX(grin_date) last, MAX(updated_at) updated FROM grin_lines"),
                  portal=_grin_portal(grin_portal)),
        payments=_one("SELECT COUNT(*) n, COUNT(DISTINCT pv) vouchers, MIN(pv_date) first, MAX(pv_date) last "
                      "FROM gp_pay_lines"),
        register=_one("SELECT COUNT(*) n, SUM(pv<>'') marked, MAX(inv_date) last, MAX(file) file, MAX(loaded_at) loaded "
                      "FROM gp_register"),
        files=rows("SELECT * FROM gp_pay_files ORDER BY id DESC LIMIT 50"),
        smtp=dict(ready=smtp_settings()["ready"], host=smtp_settings()["host"], sender=smtp_settings()["sender"]),
        dates=st.data_dates())


def _grin_portal(grin_portal):
    if config.ON_VERCEL:
        a = pc_jobs.agent_info()
        return dict(pc_jobs.status("grin_fetch"), method="pc" if a and a["online"] else "http")
    return dict(available=grin_portal.available(), method=grin_portal.method(), **grin_portal.STATUS)


@route("POST", r"/api/tally/test")
def tally_test(req):
    if config.ON_VERCEL:
        a = pc_jobs.agent_info()
        if a and a["online"]:
            raise ApiError(f"Tally is reached through the SDEW PC ({a['host']}, online). Press Pull from Tally - "
                           "the PC does it. To test the connection itself, use the hub on that PC.")
        raise ApiError("Tally is on the office PC and the SDEW PC is not connected right now - start the hub there "
                       "(start.bat with USE_CLOUD_DB=1).")
    url = (req.json.get("url") or load_settings()["tally_url"]).strip()
    try:
        names = tally.list_companies(url)
    except Exception as e:  # noqa: BLE001
        raise ApiError(f"Tally is not answering on {url}: {e}. Open TallyPrime and turn on F1 Help > Settings > "
                       f"Connectivity > Client/Server configuration: 'Both', port 9000.")
    return dict(url=url, companies=names)


@route("POST", r"/api/tally/pull")
def tally_pull(req):
    b = req.json
    s = load_settings()
    try:
        d2 = date.fromisoformat(b.get("to") or date.today().isoformat())
        d1 = date.fromisoformat(b.get("from") or (d2 - timedelta(days=45)).isoformat())
    except ValueError:
        raise ApiError("Dates must be yyyy-mm-dd")
    if d1 > d2:
        raise ApiError("From date is after To date")
    comps = b.get("companies") if b.get("companies") is not None else s["tally_companies"]
    if config.ON_VERCEL:      # Tally is on the office PC - hand the pull to it
        try:
            return dict(pc_jobs.queue("tally_pull", {"from": d1.isoformat(), "to": d2.isoformat()}), queued=True, done=False)
        except RuntimeError as e:
            raise ApiError(str(e))
    if not tally.start(s["tally_url"], comps, d1, d2, {p["party"] for p in plants()}):
        raise ApiError("A Tally pull is already running")
    st.invalidate()
    return dict(started=True)


@route("GET", r"/api/tally/pull")
def tally_status(req):
    if config.ON_VERCEL:
        st = pc_jobs.status("tally_pull")
        if not st["running"]:
            st_.invalidate()
        return st
    if not tally.STATUS["running"]:
        st.invalidate()
    return tally.STATUS


# ---- the website's "Pull from Tally": the browser asks THIS computer's Tally through tools/tally_bridge.py ----
@route("POST", r"/api/tally/plan")
def tally_plan(req):
    b = req.json
    s = load_settings()
    try:
        d2 = date.fromisoformat(b.get("to") or date.today().isoformat())
        d1 = date.fromisoformat(b.get("from") or (d2 - timedelta(days=45)).isoformat())
    except ValueError:
        raise ApiError("Dates must be yyyy-mm-dd")
    if d1 > d2:
        raise ApiError("From date is after To date")
    comps = b.get("companies") if b.get("companies") is not None else s["tally_companies"]
    return dict(chunks=tally.plan(comps, d1, d2))


@route("POST", r"/api/tally/ingest")
def tally_ingest(req):
    import base64
    import gzip
    b = req.json
    try:
        a, z = date.fromisoformat(b["from"]), date.fromisoformat(b["to"])
    except (KeyError, ValueError):
        raise ApiError("from / to missing")
    if b.get("gz"):
        text = gzip.decompress(base64.b64decode(b["gz"])).decode("utf-8", errors="replace")
    else:
        text = b.get("text") or ""
    if not text.strip():
        raise ApiError("Empty answer from Tally")
    try:
        r = tally.ingest_text(text, b.get("company") or "", a, z, {p["party"] for p in plants()}, b.get("mode") or "")
    except Exception as e:  # noqa: BLE001
        raise ApiError(f"Tally answer could not be read: {e}")
    st.invalidate()
    return r


@route("POST", r"/api/tally/done")
def tally_done(req):
    from ...db import log
    b = req.json
    log("grin", "Tally pull (website)", f"{b.get('invoices', 0)} invoices {b.get('from')} to {b.get('to')} "
        f"from {b.get('host') or 'this computer'}")
    st.invalidate()
    return dict(ok=True)


# ---- "Fetch payments from TAFE Channel" (Account Info > Payment Details, no browser) ----
@route("POST", r"/api/payments/fetch")
def payments_fetch(req):
    from ..services import pay_portal
    b = req.json
    try:
        d2 = date.fromisoformat(b.get("to") or date.today().isoformat())
        d1 = date.fromisoformat(b.get("from") or (d2 - timedelta(days=45)).isoformat())
    except ValueError:
        raise ApiError("Dates must be yyyy-mm-dd")
    if d1 > d2:
        raise ApiError("From date is after To date")
    if pay_portal.STATUS["running"]:
        raise ApiError("Already fetching payments - wait for it to finish")
    st_ = pay_portal.run(d1, d2)
    out = dict(st_)
    if out["error"] and config.ON_VERCEL and pay_portal.network_problem(out["error"]):
        a = pc_jobs.agent_info()
        if a and a["online"]:     # TAFE Channel answers Indian addresses - the SDEW PC does it
            q = pc_jobs.queue("pay_fetch", {"from": d1.isoformat(), "to": d2.isoformat()})
            q["log"] = out["log"] + ["TAFE Channel did not answer this website - asking the SDEW PC instead"] + q["log"]
            return dict(q, queued=True, done=False)
    return dict(out, done=True)


@route("GET", r"/api/payments/fetch")
def payments_fetch_status(req):
    from ..services import pay_portal
    if config.ON_VERCEL:
        j = pc_jobs.status("pay_fetch")
        if j.get("running") or (j.get("started") or "") > (pay_portal.STATUS.get("started") or ""):
            return j
    return pay_portal.STATUS


@route("GET", r"/api/payments/check")
def payments_check(req):
    data = st.build(req.arg("as_of") or None)
    return data.get("pay_check") or {}
