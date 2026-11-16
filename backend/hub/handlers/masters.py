"""Masters page API and the 8 am / 9 pm TAFE Channel sync.

  GET  /api/masters                      every master: last refresh, light, history, PO master summary
  POST /api/masters/<master>/refresh     Refresh now (body {"full": true} = PO master: 3 years)
  GET  /api/masters/po?q=&plant=&open=1  PO master lines (with rate history when searching)
  GET  /api/masters/po/compare           PO master vs the prices loaded before from PO .htm / export files
  GET  /api/cron/masters                 Vercel Cron, every 5 minutes after 8:00 and 21:00 India time
"""
import hmac
import os

from .. import config
from ..db import CURRENT_USER
from ..http import ApiError, route
from ..masters import po_master, sync


@route("GET", r"/api/masters")
def masters(req):
    return sync.overview()


@route("POST", r"/api/masters/(?P<master>[a-z]+)/refresh")
def refresh(req):
    b = req.json if req._body_bytes else {}
    try:
        r = sync.refresh(req.params["master"], user=CURRENT_USER.get() or "", full=bool((b or {}).get("full")))
    except ValueError as e:
        raise ApiError(str(e), 404)
    except RuntimeError as e:
        raise ApiError(str(e))
    return dict(run=sync._clean(r), overview=sync.overview())


@route("GET", r"/api/masters/po")
def po_lines(req):
    return dict(rows=po_master.search(req.arg("q"), req.arg("plant"), req.arg("open") == "1",
                                      limit=min(int(req.arg("limit", "500") or 500), 5000)),
                summary=po_master.summary(), plants=po_master.supplied_plants())


@route("GET", r"/api/masters/po/compare")
def po_compare(req):
    return po_master.compare()


@route("GET", r"/api/cron/masters")
def cron(req):
    secret = os.environ.get("CRON_SECRET") or config.read_env().get("CRON_SECRET") or ""
    if secret and not hmac.compare_digest((req.headers or {}).get("authorization", ""), f"Bearer {secret}"):
        raise ApiError("Not allowed", 401)
    return sync.tick("schedule (website)")
