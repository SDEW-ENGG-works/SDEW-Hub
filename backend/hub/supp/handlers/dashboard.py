from ..db import one, rows
from ..http import route
from ..services import grin_portal
from ..services.defaults import load_settings
from ..services.engine import latest_run_id
import json


def counts():
    c = lambda sql: (one(sql) or {}).get("n", 0)
    g = one("SELECT COUNT(*) n, MIN(grin_date) first, MAX(grin_date) last FROM grin_lines") or {}
    s = one("SELECT COUNT(*) n, MIN(inv_date) first, MAX(inv_date) last FROM sales_lines") or {}
    return dict(pos=c("SELECT COUNT(*) n FROM po_headers"), po_parts=c("SELECT COUNT(*) n FROM po_items"),
                grin=g.get("n", 0), grin_first=g.get("first"), grin_last=g.get("last"),
                sales=s.get("n", 0), sales_first=s.get("first"), sales_last=s.get("last"),
                files=c("SELECT COUNT(*) n FROM files"))


@route("GET", r"/api/bootstrap")
def bootstrap(req):
    rid = latest_run_id()
    run = one("SELECT id, created_at, summary, params FROM bill_runs WHERE id=?", (rid,)) if rid else None
    if run:
        run["summary"] = json.loads(run["summary"])
        run["params"] = json.loads(run["params"])
    return dict(counts=counts(), settings=load_settings(), run=run,
                portal=dict(available=grin_portal.available()))
