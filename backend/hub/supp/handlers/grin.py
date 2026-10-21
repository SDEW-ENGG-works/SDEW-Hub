from datetime import date, timedelta

from ..db import rows
from ..http import ApiError, route
from ..services import grin_portal


@route("GET", r"/api/grin/summary")
def summary(req):
    months = rows("""SELECT substr(grin_date,1,7) month, COUNT(*) lines, COUNT(DISTINCT grin_no) grins,
        SUM(source='Portal') portal, SUM(source='Upload') upload, MAX(updated_at) updated,
        SUM(accepted_qty IS NULL OR (accepted_qty=0 AND rejected_qty=0)) open_lots
        FROM grin_lines GROUP BY 1 ORDER BY 1 DESC""")
    plants = rows("SELECT plant, COUNT(*) lines FROM grin_lines GROUP BY plant ORDER BY lines DESC")
    return dict(months=months, plants=plants, portal=dict(available=grin_portal.available(), **grin_portal.STATUS))


@route("GET", r"/api/grin/search")
def search(req):
    q = f"%{req.arg('q').strip()}%"
    return rows("""SELECT * FROM grin_lines WHERE grin_no LIKE ? OR invoice_no LIKE ? OR part_no LIKE ? OR po_no LIKE ?
        ORDER BY grin_date DESC LIMIT 200""", (q, q, q, q))


@route("POST", r"/api/grin/sync")
def sync(req):
    if not grin_portal.available():
        raise ApiError("Playwright is not installed on this PC. Run:  pip install playwright  then  "
                       "python -m playwright install chromium")
    body = req.json
    try:
        d2 = date.fromisoformat(body.get("to") or date.today().isoformat())
        d1 = date.fromisoformat(body.get("from") or (d2 - timedelta(days=45)).isoformat())
    except ValueError:
        raise ApiError("Dates must be yyyy-mm-dd")
    if d1 > d2:
        raise ApiError("From date is after To date")
    if not grin_portal.start(d1, d2, headed=bool(body.get("headed"))):
        raise ApiError("A GRIN sync is already running")
    return dict(started=True)


@route("GET", r"/api/grin/sync")
def sync_status(req):
    return grin_portal.STATUS
