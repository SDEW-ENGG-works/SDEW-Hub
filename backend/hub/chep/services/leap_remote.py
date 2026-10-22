"""LEAP from the website. The browser automation can only run on the SDEW PC, so:

  website (Vercel)  -> puts a job in the shared Turso table leap_jobs, then shows the job's
                       state and writes the user's Submit / Cancel into it. The button works
                       even while the PC is off: the job waits until the PC picks it up.
  SDEW PC app       -> (with USE_CLOUD_DB=1 and Playwright) a background "agent" says it is
                       online every few seconds, picks up queued jobs, runs them with leap.py and
                       copies the live steps back into leap_jobs; a Submit pressed on the website
                       reaches the PC through the same row.

The agent serves EVERY database a website may read the CHEP pages from: the hub's database
(what the PC itself uses) and, when CHEP_TURSO_DATABASE_URL is in .env and is a different
database, the old CHEP website's database. So the button works whichever website is open and
whichever database Vercel is set to.
Jobs started on the PC itself are copied to leap_jobs too, so the website can follow them.
"""
import json
import socket
import threading
import time
import traceback
from datetime import datetime

from .. import config
from .. import db as cdb
from ..db import get_db, get_setting, one, set_setting
from . import leap

POLL = 4          # s between looks for new jobs when idle
FAST = 1.5        # s between updates while a job runs
BEAT = 20         # s between "PC is online" notes
ONLINE = 75       # PC counts as online if its last note is newer than this
STALE = 120       # a running job with no update for this long = PC stopped answering
QUEUE_MAX = 6 * 3600   # a job nobody picked up for 6 h is dropped (not started hours later)

_agent_on = False
_job = None       # (spec, job_id) of the job the agent is following


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _ago(sec):
    sec = int(sec)
    if sec < 90:
        return f"{sec} s ago"
    if sec < 5400:
        return f"{sec // 60} min ago"
    if sec < 2 * 86400:
        return f"{sec // 3600} h ago"
    return f"{sec // 86400} days ago"


# ---------------------------------------------------------------- shared
def agent_info():
    a = get_setting("leap_agent")
    if not a or not a.get("ts"):
        return dict(host="", age=None, online=False, seen="never")
    age = max(0, time.time() - float(a["ts"]))
    return dict(host=a.get("host", ""), age=int(age), online=age < ONLINE, seen=_ago(age))


def latest_job():
    return one("SELECT * FROM leap_jobs ORDER BY id DESC LIMIT 1")


# ---------------------------------------------------------------- website side
def runner():
    """'pc' or 'cloud' - who does the next upload started on the website.
    LEAP_RUNNER = auto (PC when it is online, else the Vercel cloud browser) | cloud | pc."""
    from . import leap_cloud
    mode = (config.read_env().get("LEAP_RUNNER") or "auto").strip().lower()
    cloud_ok = leap_cloud.usable()[0]
    if mode == "pc" or not cloud_ok:
        return "pc"
    if mode == "cloud":
        return "cloud"
    return "pc" if agent_info()["online"] else "cloud"


def remote_available():
    """The button is always usable on the website - when the PC is off the job just waits."""
    a = agent_info()
    if a["online"] or runner() == "cloud":
        return True, ""
    from . import leap_cloud
    cloud_ok, cloud_why = leap_cloud.usable()
    extra = "" if cloud_ok or not config.ON_VERCEL else f" (The cloud browser can't be used: {cloud_why}.)"
    return True, (f"The SDEW PC is not connected right now (last seen: {a['seen']}). You can still press "
                  "Upload - it starts as soon as the SDEW Hub app (start.bat) is running on the PC." + extra)


def _active(j):
    if not j:
        return False
    if j["status"] == "starting":
        return time.time() - float(j["updated_ts"] or 0) < 600
    if j["status"] == "queued":
        return time.time() - float(j["updated_ts"] or 0) < QUEUE_MAX
    return j["status"] in ("running", "waiting") and time.time() - float(j["updated_ts"] or 0) < STALE


def remote_start(run_id, mode, headed):
    if _active(latest_job()):
        raise RuntimeError("LEAP is already busy with another file - wait for it to finish or press Stop.")
    run = one("SELECT id, file_name FROM chep_runs WHERE id=?", (run_id,))
    if not run:
        raise RuntimeError("That file is not in History any more.")
    who = runner()
    status = "starting" if who == "cloud" else "queued"   # 'starting' = for the cloud browser only
    con = get_db()
    cur = con.execute("INSERT INTO leap_jobs(run_id, mode, headed, status, state, decision, created_at, updated_ts) "
                      "VALUES(?,?,?,?,?,?,?,?)",
                      (run_id, mode, 1 if headed else 0, status,
                       json.dumps(dict(file_name=run["file_name"], runner=who)), None, _now(), time.time()))
    con.commit()
    if who == "cloud":
        from . import leap_cloud
        try:
            leap_cloud.launch(cur.lastrowid)
        except RuntimeError as e:
            con.execute("UPDATE leap_jobs SET status='error', state=?, updated_ts=? WHERE id=?",
                        (json.dumps(dict(active=False, phase="error", error=str(e), mode=mode,
                                         file_name=run["file_name"], steps=[], log=[str(e)])),
                         time.time(), cur.lastrowid))
            con.commit()
            raise
    return remote_snapshot()


def remote_snapshot():
    j = latest_job()
    if not j:
        return dict(active=False, phase="idle")
    st = json.loads(j["state"] or "{}")
    age = time.time() - float(j["updated_ts"] or 0)
    if j["status"] == "starting" and st.get("steps"):
        st["phase"] = "running"     # the cloud browser is installing - its own steps are shown
        if time.time() - float(j["updated_ts"] or 0) > 600:
            st.update(phase="error", error="The cloud browser stopped answering while installing.")
    elif j["status"] == "starting":
        st = dict(active=True, phase="running", mode=j["mode"], file_name=st.get("file_name", ""),
                  run_id=j["run_id"], runner="cloud",
                  steps=[dict(key="pc", label="Start the cloud browser (Vercel)", status="doing",
                              detail="Starting… the very first run installs Chromium and takes about 3 minutes")],
                  parts=[], current=None, log=[], verify=None)
        if age > 600:
            st.update(phase="error", error="The cloud browser did not start within 10 minutes.")
            st["steps"][0].update(status="error", detail=st["error"])
    elif j["status"] == "queued":
        a = agent_info()
        if age > QUEUE_MAX:
            st = dict(active=False, phase="cancelled", mode=j["mode"], file_name=st.get("file_name", ""),
                      steps=[], log=["Not started - the SDEW PC did not pick it up within 6 hours"])
        else:
            detail = ("The PC is picking it up…" if a["online"] else
                      f"Waiting for the SDEW PC - start the SDEW Hub app there (last seen: {a['seen']})")
            st = dict(active=True, phase="running", mode=j["mode"], file_name=st.get("file_name", ""),
                      run_id=j["run_id"], steps=[dict(key="pc", label="Sent to the SDEW PC", status="doing",
                                                      detail=detail)],
                      parts=[], current=None, log=[], verify=None)
    elif j["status"] in ("running", "waiting") and age > STALE:
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
    con = get_db()
    if j and j["status"] in ("queued", "starting"):
        con.execute("UPDATE leap_jobs SET status='cancelled', state=?, updated_ts=? WHERE id=?",
                    (json.dumps(dict(active=False, phase="cancelled", mode=j["mode"],
                                     file_name=json.loads(j["state"] or "{}").get("file_name", ""),
                                     steps=[], log=["Cancelled before the PC started it"])), time.time(), j["id"]))
        con.commit()
    elif _active(j):
        con.execute("UPDATE leap_jobs SET decision='cancel' WHERE id=?", (j["id"],))
        con.commit()
    return remote_snapshot()


# ---------------------------------------------------------------- PC side
def agent_running():
    return _agent_on


def _targets():
    """[(label, spec)] - spec None = the CHEP database this PC app uses itself."""
    from ... import config as hub
    from ... import db as hubdb
    out = [("this PC's database", None)]
    env = hub.read_env()
    mine = (hub.cloud_db() or hub.module_cloud_db("chep") or (None,))[0]
    url, token = env.get("CHEP_TURSO_DATABASE_URL"), env.get("CHEP_TURSO_AUTH_TOKEN")
    if url and token and url != mine:
        def factory(url=url, token=token):
            from ...turso import Connection
            return hubdb.ModuleConnection(Connection(url, token), hubdb.MODULE_RENAMES.get("chep", {}))
        out.append(("the old CHEP website's database", ("chep-site", factory, False)))
    return out


def start_agent():
    """Called once when the PC app starts. Does nothing on Vercel, with the PC's own database,
    or when Playwright / the LEAP login are missing."""
    global _agent_on
    if _agent_on or config.ON_VERCEL or config.db_mode() != "cloud":
        if not config.ON_VERCEL and config.db_mode() != "cloud":
            print("[LEAP agent] not started: USE_CLOUD_DB=1 is not in .env, so the website can't reach this PC")
        return
    ok, why = leap.available()
    if not ok:
        print(f"[LEAP agent] not started: {why}")
        return
    _agent_on = True
    targets = _targets()
    threading.Thread(target=_loop, args=(targets,), daemon=True, name="leap-agent").start()
    print("[LEAP agent] on - the website can now send LEAP uploads to this PC "
          f"(watching {' and '.join(t[0] for t in targets)})")


def track_local(run_id, mode, headed):
    """A job started on the PC page: give it a leap_jobs row so the website can follow it."""
    global _job
    if not _agent_on:
        return
    try:
        con = get_db()
        cur = con.execute("INSERT INTO leap_jobs(run_id, mode, headed, status, state, decision, created_at, updated_ts) "
                          "VALUES(?,?,?,?,?,?,?,?)",
                          (run_id, mode, 1 if headed else 0, "running", json.dumps(leap.snapshot()), None,
                           _now(), time.time()))
        con.commit()
        _job = (cdb.current(), cur.lastrowid)
    except Exception:  # noqa: BLE001 - the upload itself must not fail because of this
        traceback.print_exc()


def _status(phase):
    return phase if phase in ("running", "waiting", "done", "error", "cancelled") else "running"


def _commit():
    get_db().commit()


def _follow_once(jid, mem):
    """Pass Submit/Cancel from leap_jobs to leap.py and copy leap.py's state into leap_jobs.
    Returns True while the job is still going."""
    j = one("SELECT decision FROM leap_jobs WHERE id=?", (jid,))
    if j and j["decision"]:
        get_db().execute("UPDATE leap_jobs SET decision=NULL WHERE id=?", (jid,))
        _commit()
        try:
            if leap.STATE.get("phase") == "waiting":
                leap.decide(j["decision"])
            elif j["decision"] == "cancel":
                leap.cancel()
        except RuntimeError:
            pass
    going = bool(leap.STATE.get("active")) and leap.STATE.get("phase") in ("running", "waiting")
    text = json.dumps(leap.snapshot())
    now = time.time()
    if text != mem.get("text") or now - mem.get("at", 0) > 15 or not going:
        get_db().execute("UPDATE leap_jobs SET status=?, state=?, updated_ts=? WHERE id=?",
                         (_status(leap.STATE.get("phase")), text, now, jid))
        _commit()
        mem.update(text=text, at=now)
    return going


def follow_job(spec, jid):
    """Blocking: follow job jid until leap.py has finished (used in the cloud browser)."""
    cdb.use(spec)
    mem, errors = {}, 0
    while True:
        try:
            if not _follow_once(jid, mem):
                break
            errors = 0
        except Exception:  # noqa: BLE001 - internet hiccup: try again
            errors += 1
            traceback.print_exc()
            if errors > 100 and not leap.STATE.get("active"):
                break
        time.sleep(FAST)


def _loop(targets):
    global _job
    host = socket.gethostname()
    last_beat = {}
    mem = {}
    warned = set()
    while True:
        now = time.time()
        phase = leap.STATE.get("phase")
        busy = bool(leap.STATE.get("active")) and phase in ("running", "waiting")
        for label, spec in targets:
            cdb.use(spec)
            try:
                if now - last_beat.get(label, 0) > BEAT:
                    set_setting("leap_agent", dict(host=host, ts=now, at=_now()))
                    last_beat[label] = now
                    warned.discard(label)
                if _job and _job[0] is spec:
                    if not _follow_once(_job[1], mem):
                        _job = None
                        mem = {}
                elif not _job and not busy:
                    j = one("SELECT id, run_id, mode, headed, updated_ts FROM leap_jobs WHERE status='queued' "
                            "ORDER BY id DESC LIMIT 1")
                    if j and now - float(j["updated_ts"] or 0) > QUEUE_MAX:
                        j = None
                    if j:
                        get_db().execute("UPDATE leap_jobs SET status='running', updated_ts=? "
                                         "WHERE id=? AND status='queued'", (time.time(), j["id"]))
                        _commit()
                        print(f"[LEAP agent] job {j['id']} from the website ({label}): "
                              f"{j['mode']} History file {j['run_id']}")
                        try:
                            leap.start(j["run_id"], j["mode"], bool(j["headed"]))
                            _job = (spec, j["id"])
                            busy = True
                        except RuntimeError as e:
                            get_db().execute("UPDATE leap_jobs SET status='error', state=?, updated_ts=? WHERE id=?",
                                             (json.dumps(dict(active=False, phase="error", error=str(e), mode=j["mode"],
                                                              steps=[], log=[f"PC: {e}"])), time.time(), j["id"]))
                            _commit()
            except Exception as e:  # noqa: BLE001 - keep the agent alive (internet down for a moment, ...)
                if label not in warned:
                    print(f"[LEAP agent] {label}: {e}")
                    traceback.print_exc()
                    warned.add(label)
            finally:
                cdb.use(None)
        time.sleep(FAST if _job else POLL)
