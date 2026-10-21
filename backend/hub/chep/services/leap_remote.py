"""LEAP from the website. The browser automation can only run on the SDEW PC, so:

  website (Vercel)  -> puts a job in the shared Turso table leap_jobs, then shows the job's
                       state and writes the user's Submit / Cancel into it
  SDEW PC app       -> (with USE_CLOUD_DB=1 and Playwright) a background "agent" says it is
                       online every few seconds, picks up queued jobs, runs them with leap.py and
                       copies the live steps back into leap_jobs; a Submit pressed on the website
                       reaches the PC through the same row.
Jobs started on the PC itself are copied to leap_jobs too, so the website can follow them.
"""
import json
import socket
import threading
import time
import traceback
from datetime import datetime

from .. import config
from ..db import get_db, get_setting, one, set_setting
from . import leap

POLL = 4          # s between looks for new jobs when idle
FAST = 1.5        # s between updates while a job runs
BEAT = 20         # s between "PC is online" notes
ONLINE = 75       # PC counts as online if its last note is newer than this
STALE = 120       # a running job with no update for this long = PC stopped answering

_agent_on = False
_job_id = None


def _now():
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- shared
def agent_info():
    a = get_setting("leap_agent")
    if not a or not a.get("ts"):
        return None
    age = time.time() - float(a["ts"])
    return dict(host=a.get("host", ""), age=int(age), online=age < ONLINE)


def latest_job():
    return one("SELECT * FROM leap_jobs ORDER BY id DESC LIMIT 1")


# ---------------------------------------------------------------- website side
def remote_available():
    a = agent_info()
    if a and a["online"]:
        return True, ""
    return False, ("The LEAP upload runs on the SDEW PC. Start the CHEP app there (start.bat, with "
                   "USE_CLOUD_DB=1 in .env) - this button works here as soon as it is running.")


def _active(j):
    return j and j["status"] in ("queued", "running", "waiting") and \
        time.time() - float(j["updated_ts"] or 0) < STALE


def remote_start(run_id, mode, headed):
    ok, why = remote_available()
    if not ok:
        raise RuntimeError(why)
    if _active(latest_job()):
        raise RuntimeError("LEAP is already busy with another file - wait for it to finish or press Stop.")
    run = one("SELECT id, file_name FROM chep_runs WHERE id=?", (run_id,))
    if not run:
        raise RuntimeError("That file is not in History any more.")
    con = get_db()
    con.execute("INSERT INTO leap_jobs(run_id, mode, headed, status, state, decision, created_at, updated_ts) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (run_id, mode, 1 if headed else 0, "queued", json.dumps(dict(file_name=run["file_name"])),
                 None, _now(), time.time()))
    con.commit()
    return remote_snapshot()


def remote_snapshot():
    j = latest_job()
    if not j:
        return dict(active=False, phase="idle")
    st = json.loads(j["state"] or "{}")
    if j["status"] == "queued":
        st = dict(active=True, phase="running", mode=j["mode"], file_name=st.get("file_name", ""),
                  run_id=j["run_id"], steps=[dict(key="pc", label="Sent to the SDEW PC", status="doing",
                                                  detail="Waiting for the PC app to pick it up")],
                  parts=[], current=None, log=[], verify=None)
    age = time.time() - float(j["updated_ts"] or 0)
    if j["status"] in ("queued", "running", "waiting") and age > STALE:
        st["phase"] = "error"
        st["error"] = "The SDEW PC stopped answering (app closed or no internet)."
        st.setdefault("log", []).append(st["error"])
    if j["decision"] and st.get("phase") == "waiting":
        st["phase"] = "running"   # Submit/Cancel pressed - the PC picks it up in a moment
    st.update(job_id=j["id"], remote=True, updated_age=int(age))
    return st


def remote_decide(choice):
    j = latest_job()
    if not j or j["status"] != "waiting":
        raise RuntimeError("Nothing is waiting for a decision.")
    con = get_db()
    con.execute("UPDATE leap_jobs SET decision=? WHERE id=?", (choice, j["id"]))
    con.commit()
    return remote_snapshot()


def remote_cancel():
    j = latest_job()
    if j and j["status"] == "queued":
        con = get_db()
        con.execute("UPDATE leap_jobs SET status='cancelled', state=?, updated_ts=? WHERE id=?",
                    (json.dumps(dict(active=False, phase="cancelled", mode=j["mode"],
                                     file_name=json.loads(j["state"] or "{}").get("file_name", ""),
                                     steps=[], log=["Cancelled before the PC started it"])), time.time(), j["id"]))
        con.commit()
    elif _active(j):
        con = get_db()
        con.execute("UPDATE leap_jobs SET decision='cancel' WHERE id=?", (j["id"],))
        con.commit()
    return remote_snapshot()


# ---------------------------------------------------------------- PC side
def agent_running():
    return _agent_on


def start_agent():
    """Called once when the PC app starts. Does nothing on Vercel, with the PC's own database,
    or when Playwright / the LEAP login are missing."""
    global _agent_on
    if _agent_on or config.ON_VERCEL or config.db_mode() != "cloud":
        return
    ok, why = leap.available()
    if not ok:
        print(f"[LEAP agent] not started: {why}")
        return
    _agent_on = True
    threading.Thread(target=_loop, daemon=True, name="leap-agent").start()
    print("[LEAP agent] on - the website can now send LEAP uploads to this PC")


def track_local(run_id, mode, headed):
    """A job started on the PC page: give it a leap_jobs row so the website can follow it."""
    global _job_id
    if not _agent_on:
        return
    try:
        con = get_db()
        cur = con.execute("INSERT INTO leap_jobs(run_id, mode, headed, status, state, decision, created_at, updated_ts) "
                          "VALUES(?,?,?,?,?,?,?,?)",
                          (run_id, mode, 1 if headed else 0, "running", json.dumps(leap.snapshot()), None,
                           _now(), time.time()))
        con.commit()
        _job_id = cur.lastrowid
    except Exception:  # noqa: BLE001 - the upload itself must not fail because of this
        traceback.print_exc()


def _status(phase):
    return phase if phase in ("running", "waiting", "done", "error", "cancelled") else "running"


def _loop():
    global _job_id
    host = socket.gethostname()
    last_beat, last_push, last_text = 0.0, 0.0, None
    while True:
        try:
            now = time.time()
            if now - last_beat > BEAT:
                set_setting("leap_agent", dict(host=host, ts=now, at=_now()))
                last_beat = now
            phase = leap.STATE.get("phase")
            busy = bool(leap.STATE.get("active")) and phase in ("running", "waiting")
            if _job_id:
                j = one("SELECT decision FROM leap_jobs WHERE id=?", (_job_id,))
                if j and j["decision"]:
                    con = get_db()
                    con.execute("UPDATE leap_jobs SET decision=NULL WHERE id=?", (_job_id,))
                    con.commit()
                    try:
                        if phase == "waiting":
                            leap.decide(j["decision"])
                        elif j["decision"] == "cancel":
                            leap.cancel()
                    except RuntimeError:
                        pass
                    phase = leap.STATE.get("phase")
                text = json.dumps(leap.snapshot())
                if text != last_text or now - last_push > 15:
                    con = get_db()
                    con.execute("UPDATE leap_jobs SET status=?, state=?, updated_ts=? WHERE id=?",
                                (_status(phase), text, time.time(), _job_id))
                    con.commit()
                    last_text, last_push = text, now
                if not busy:
                    _job_id, last_text = None, None
            elif not busy:
                j = one("SELECT id, run_id, mode, headed FROM leap_jobs WHERE status='queued' ORDER BY id LIMIT 1")
                if j:
                    con = get_db()
                    con.execute("UPDATE leap_jobs SET status='running', updated_ts=? WHERE id=? AND status='queued'",
                                (time.time(), j["id"]))
                    con.commit()
                    print(f"[LEAP agent] job {j['id']} from the website: {j['mode']} History file {j['run_id']}")
                    try:
                        leap.start(j["run_id"], j["mode"], bool(j["headed"]))
                        _job_id = j["id"]
                    except RuntimeError as e:
                        con.execute("UPDATE leap_jobs SET status='error', state=?, updated_ts=? WHERE id=?",
                                    (json.dumps(dict(active=False, phase="error", error=str(e), mode=j["mode"],
                                                     steps=[], log=[f"PC: {e}"])), time.time(), j["id"]))
                        con.commit()
        except Exception:  # noqa: BLE001 - keep the agent alive (e.g. internet down for a moment)
            traceback.print_exc()
        time.sleep(FAST if _job_id else POLL)
