import json

from ..db import one
from ..http import ApiError, route
from .. import config
from ..services import leap, leap_remote as remote


def _remote():
    """True on the website (and on a PC without Playwright that shares the website's data):
    the job is handed to the SDEW PC through the shared database."""
    if config.ON_VERCEL:
        return True
    return not leap.available()[0] and config.db_mode() == "cloud"


@route("GET", r"/api/leap/status")
def status(req):
    if _remote():
        ok, why = remote.remote_available()
        return dict(available=ok, reason=why, remote=True, agent=remote.agent_info(), state=remote.remote_snapshot())
    ok, why = leap.available()
    return dict(available=ok, reason=why, remote=False, state=leap.snapshot())


@route("POST", r"/api/leap/start")
def start(req):
    b = req.json
    mode = b.get("mode", "upload")
    if mode not in ("upload", "verify"):
        raise ApiError("mode must be upload or verify")
    run_id, headed = int(b.get("run_id") or 0), bool(b.get("headed"))
    try:
        if _remote():
            return remote.remote_start(run_id, mode, headed)
        st = leap.start(run_id, mode, headed)
        remote.track_local(run_id, mode, headed)
        return st
    except RuntimeError as e:
        raise ApiError(str(e))


@route("POST", r"/api/leap/decide")
def decide(req):
    choice = req.json.get("choice")
    if choice not in ("submit", "cancel"):
        raise ApiError("choice must be submit or cancel")
    try:
        return remote.remote_decide(choice) if _remote() else leap.decide(choice)
    except RuntimeError as e:
        raise ApiError(str(e))


@route("POST", r"/api/leap/cancel")
def cancel(req):
    return remote.remote_cancel() if _remote() else leap.cancel()


@route("GET", r"/api/runs/(?P<id>\d+)/leap")
def run_result(req):
    r = one("SELECT id, file_name, leap_status, leap_at, leap_result FROM chep_runs WHERE id=?", (int(req.params["id"]),))
    if not r:
        raise ApiError("Not found", 404)
    r["leap_result"] = json.loads(r["leap_result"] or "{}")
    return r
