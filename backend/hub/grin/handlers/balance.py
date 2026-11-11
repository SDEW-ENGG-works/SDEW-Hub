"""TAFE outstanding (Account Balance-Outstanding on TAFE Channel): dashboard, fetch, daily cron."""
import hmac
import os
from datetime import datetime, timedelta

from .. import route
from ... import config
from ...http import ApiError
from ...http import route as hub_route
from ...services import pc_jobs
from ..services import balance
from ..services import balance_portal as bp


@route("GET", r"/api/balance")
def balance_dashboard(req):
    d = balance.dashboard()
    d["fetch"] = _status()
    return d


def _status():
    if config.ON_VERCEL:
        j = pc_jobs.status("balance_fetch")
        if j.get("running") or (j.get("started") or "") > (bp.STATUS.get("started") or ""):
            return j
    return bp.STATUS


@route("GET", r"/api/balance/fetch")
def balance_fetch_status(req):
    return _status()


def _fetch(source):
    if bp.STATUS["running"]:
        raise ApiError("Already fetching the TAFE balance - wait a moment")
    if not config.ON_VERCEL:
        bp.start()
        return dict(bp.STATUS, done=False)
    st = dict(bp.run(source))                    # three requests - quick enough for the website
    if st["error"] and bp.network_problem(st["error"]):
        a = pc_jobs.agent_info()
        if a and a["online"]:
            q = pc_jobs.queue("balance_fetch", {"from": "", "to": ""})
            q["log"] = st["log"] + ["TAFE Channel did not answer this website - asking the SDEW PC instead"] + q["log"]
            return dict(q, queued=True, done=False)
    return dict(st, done=True)


@route("POST", r"/api/balance/fetch")
def balance_fetch(req):
    return _fetch("manual")


@hub_route("GET", r"/api/cron/tafe-balance")
def cron_balance(req):
    """Vercel Cron, once a day (vercel.json). With CRON_SECRET set only Vercel may call it; without it, at most
    once per 6 hours."""
    secret = os.environ.get("CRON_SECRET") or config.read_env().get("CRON_SECRET") or ""
    if secret:
        if not hmac.compare_digest((req.headers or {}).get("authorization", ""), f"Bearer {secret}"):
            raise ApiError("Not allowed", 401)
    else:
        from ..db import one
        last = one("SELECT fetched_at FROM gp_bal_runs ORDER BY id DESC LIMIT 1")
        if last and last["fetched_at"] > (datetime.now() - timedelta(hours=6)).isoformat(timespec="seconds"):
            return dict(ok=True, skipped=f"fetched at {last['fetched_at']}")
    r = _fetch("daily (website)")
    return dict(ok=not r.get("error"), queued=r.get("queued", False), error=r.get("error", ""), result=r.get("result"))
