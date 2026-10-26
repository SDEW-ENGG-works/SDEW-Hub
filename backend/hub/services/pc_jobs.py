"""Work the website cannot do itself is handed to the SDEW PC through the shared (primary) database.

  Pull from Tally   Tally answers only on the office PC (localhost:9000)
  Fetch GRIN        TAFE Channel answers Indian addresses / the browser runs only on the PC
  DQMS report       only when the website itself cannot reach TAFE Channel

  website (Vercel)  -> INSERT a row in pc_jobs (status 'queued') and shows that row's log
  SDEW PC (start.bat with USE_CLOUD_DB=1 + TURSO_* of the primary database)
                    -> an agent thread says "online" every 20 s (setting hub.pc_agent), picks up queued
                       jobs, runs them with the normal PC code and copies its log into the row.
"""
import json
import socket
import threading
import time
import traceback
from datetime import date, datetime

from .. import config
from ..db import get_db, get_setting, one, set_setting

POLL = 4
BEAT = 20
ONLINE = 75       # PC counts as online if it said so within this many seconds
STALE = 180       # a queued/running job not touched for this long -> given up
KINDS = ("tally_pull", "grin_fetch", "dqms_report", "pay_fetch", "notes_fetch")
_on = False


def _now():
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------ website side
def agent_info():
    a = get_setting("hub.pc_agent")
    if not a or not a.get("ts"):
        return None
    age = time.time() - float(a["ts"])
    return dict(host=a.get("host", ""), at=a.get("at", ""), age=int(age), online=age < ONLINE)


def latest(kind):
    return one("SELECT * FROM pc_jobs WHERE kind=? ORDER BY id DESC LIMIT 1", (kind,))


def _active(j):
    return bool(j) and j["status"] in ("queued", "running") and time.time() - float(j["updated_ts"] or 0) < STALE


def queue(kind, params):
    """-> status dict. Raises RuntimeError with a plain message when the PC is not there."""
    a = agent_info()
    if not a or not a["online"]:
        seen = f" (last seen {a['at'].replace('T', ' ')})" if a and a.get("at") else ""
        raise RuntimeError("This runs on the SDEW PC, and the PC is not connected right now" + seen + ". "
                           "Start the hub there with start.bat (USE_CLOUD_DB=1 and the TURSO_* keys in .env).")
    if _active(latest(kind)):
        return status(kind)
    con = get_db()
    con.execute("INSERT INTO pc_jobs(kind, params, status, log, created_at, updated_ts) VALUES(?,?,?,?,?,?)",
                (kind, json.dumps(params), "queued", json.dumps([f"{datetime.now():%H:%M:%S}  Sent to the SDEW PC ({a['host']})"]),
                 _now(), time.time()))
    con.commit()
    return status(kind)


def status(kind):
    """The newest job of this kind in the same shape as tally.STATUS / grin_portal.STATUS."""
    j = latest(kind)
    a = agent_info()
    base = dict(running=False, log=[], started="", finished="", error="", result=None, remote=True,
                agent=a, available=True)
    if not j:
        return base
    log = json.loads(j["log"] or "[]")
    running = _active(j)
    err = j["error"] or ""
    if j["status"] in ("queued", "running") and not running:
        err = err or "The SDEW PC stopped answering - check that the hub is still running there."
    if j["status"] == "queued" and running:
        log = log + ["Waiting for the SDEW PC to pick it up…"]
    return dict(base, running=running, log=log, started=j["created_at"] or "", finished=j["finished_at"] or "",
                error=err, result=json.loads(j["result"]) if j["result"] else None, job_id=j["id"], job=j["status"])


# ------------------------------------------------------------------ PC side
def start_agent():
    """Called once by start.bat's server. Only on the PC, and only when it shares the primary cloud database."""
    global _on
    if _on or config.ON_VERCEL or not config.cloud_db():
        return
    _on = True
    threading.Thread(target=_loop, daemon=True, name="pc-jobs").start()
    print("[PC jobs] on - the website can now send 'Pull from Tally' and 'Fetch GRIN' to this PC")


def _push(job_id, st, final=False):
    con = get_db()
    con.execute("UPDATE pc_jobs SET log=?, error=?, result=?, status=?, finished_at=?, updated_ts=? WHERE id=?",
                (json.dumps(st.get("log") or []), st.get("error") or "",
                 json.dumps(st.get("result")) if st.get("result") is not None else None,
                 ("error" if st.get("error") else "done") if final else "running",
                 _now() if final else None, time.time(), job_id))
    con.commit()


def _run(job):
    p = json.loads(job["params"] or "{}")
    if job["kind"] == "dqms_report":
        from ..dqms.services import dqms_portal
        mod, started = dqms_portal, dqms_portal.start()
        _push(job["id"], dict(mod.STATUS), final=True)
        return
    d1, d2 = date.fromisoformat(p["from"]), date.fromisoformat(p["to"])
    if job["kind"] == "notes_fetch":
        from ..grin.services import notes_portal
        mod, started = notes_portal, notes_portal.start(d1, d2)
    elif job["kind"] == "pay_fetch":
        from ..grin.services import pay_portal
        mod, started = pay_portal, pay_portal.start(d1, d2)
    elif job["kind"] == "tally_pull":
        from ..grin.services import tally
        from ..grin.services.defaults import load_settings, plants
        s = load_settings()
        mod, started = tally, tally.start(s["tally_url"], s["tally_companies"], d1, d2, {x["party"] for x in plants()})
    else:
        from ..supp.services import grin_portal
        mod, started = grin_portal, grin_portal.start(d1, d2, headed=False)
    if not started:
        _push(job["id"], dict(log=["Already running on the PC - wait and press again"], error="busy"), final=True)
        return
    last = None
    while True:
        st = dict(mod.STATUS)
        text = json.dumps(st.get("log"))
        if text != last:
            _push(job["id"], st)
            last = text
        if not st.get("running"):
            break
        time.sleep(1.5)
    _push(job["id"], dict(mod.STATUS), final=True)
    try:
        from ..grin.services import status as gst
        gst.invalidate()
    except Exception:  # noqa: BLE001
        pass


def _loop():
    host = socket.gethostname()
    last_beat = 0.0
    while True:
        try:
            now = time.time()
            if now - last_beat > BEAT:
                set_setting("hub.pc_agent", dict(host=host, ts=now, at=_now()))
                last_beat = now
            j = one("SELECT * FROM pc_jobs WHERE status='queued' ORDER BY id LIMIT 1")
            if j:
                con = get_db()
                con.execute("UPDATE pc_jobs SET status='running', started_at=?, host=?, updated_ts=? "
                            "WHERE id=? AND status='queued'", (_now(), host, time.time(), j["id"]))
                con.commit()
                if time.time() - float(j["updated_ts"] or 0) > STALE:
                    _push(j["id"], dict(log=json.loads(j["log"] or "[]"), error="Too old - press the button again"), final=True)
                    continue
                try:
                    _run(j)
                except Exception as e:  # noqa: BLE001
                    traceback.print_exc()
                    _push(j["id"], dict(log=[f"Stopped: {e}"], error=str(e)), final=True)
                continue
        except Exception:  # noqa: BLE001 - network hiccup: try again next round
            traceback.print_exc()
        time.sleep(POLL)
