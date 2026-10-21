from datetime import date, timedelta

from ..db import rows
from ..http import ApiError, route
from ... import config
from ...services import pc_jobs
from ..services import grin_portal


@route("GET", r"/api/grin/summary")
def summary(req):
    months = rows("""SELECT substr(grin_date,1,7) month, COUNT(*) lines, COUNT(DISTINCT grin_no) grins,
        SUM(source='Portal') portal, SUM(source='Upload') upload, MAX(updated_at) updated,
        SUM(accepted_qty IS NULL OR (accepted_qty=0 AND rejected_qty=0)) open_lots
        FROM grin_lines GROUP BY 1 ORDER BY 1 DESC""")
    plants = rows("SELECT plant, COUNT(*) lines FROM grin_lines GROUP BY plant ORDER BY lines DESC")
    if config.ON_VERCEL:
        a = pc_jobs.agent_info()
        portal = dict(pc_jobs.status("grin_fetch"), method="pc" if a and a["online"] else "http")
    else:
        portal = dict(available=grin_portal.available(), method=grin_portal.method(), **grin_portal.STATUS)
    return dict(months=months, plants=plants, portal=portal)


@route("GET", r"/api/grin/search")
def search(req):
    q = f"%{req.arg('q').strip()}%"
    return rows("""SELECT * FROM grin_lines WHERE grin_no LIKE ? OR invoice_no LIKE ? OR part_no LIKE ? OR po_no LIKE ?
        ORDER BY grin_date DESC LIMIT 200""", (q, q, q, q))


@route("POST", r"/api/grin/sync")
def sync(req):
    body = req.json
    try:
        d2 = date.fromisoformat(body.get("to") or date.today().isoformat())
        d1 = date.fromisoformat(body.get("from") or (d2 - timedelta(days=45)).isoformat())
    except ValueError:
        raise ApiError("Dates must be yyyy-mm-dd")
    if d1 > d2:
        raise ApiError("From date is after To date")
    if config.ON_VERCEL:
        a = pc_jobs.agent_info()
        if a and a["online"]:      # the SDEW PC fetches it (browser, Indian address) into the shared database
            try:
                return dict(pc_jobs.queue("grin_fetch", {"from": d1.isoformat(), "to": d2.isoformat()}), queued=True, done=False)
            except RuntimeError as e:
                raise ApiError(str(e))
    if not grin_portal.start(d1, d2, headed=bool(body.get("headed"))):
        raise ApiError("A GRIN sync is already running")
    st = grin_portal.STATUS
    return dict(started=True, done=not st["running"], **st)


@route("GET", r"/api/grin/sync")
def sync_status(req):
    if config.ON_VERCEL:
        return pc_jobs.status("grin_fetch")
    return grin_portal.STATUS
