"""The TAFE Channel sync: every master refreshed automatically at 8 am and 9 pm (India time), and on demand.

  Masters, in this order (one at a time, so each fits in one website call):
    po        PO Details               each supplied plant, the last 12 months (3 years on Sunday night)
    grin      GRIN Details             the last 45 days
    payments  Payment Details          the last 60 days
    notes     Debit / Credit Notes     the last 45 days
    balance   Account Balance-Outstanding (full)
    dqms      DQMS Batch Details Report (full)
  Tally invoices are NOT here: they come when Tally is connected (Tally bridge) or with Pull from Tally.

Who runs it: the website (Vercel Cron calls /api/cron/masters every 5 minutes in the hours after 8 am and
9 pm) and the SDEW PC hub (a loop, every minute). Both use the same sync_runs table: a run is claimed with a
unique row (slot, master, try), so each master runs once per slot whoever is first. A master that failed is
tried again (up to 3 tries, 10 minutes apart); one that was cut short by the website's time limit carries on.
The module buttons (Fetch GRIN, Fetch payments ...) work exactly as before; Refresh now on the Masters page
runs one master at once.
"""
import json
import os
import socket
import threading
import time
import traceback
import uuid
from datetime import date, datetime, timedelta

from .. import config
from ..db import get_db, one, rows

SLOTS = ((8, 0), (21, 0))            # India time
WINDOW_MIN = 150                     # a slot's masters may still start this long after the slot time
ORDER = ("po", "grin", "payments", "notes", "balance", "dqms")
LABELS = dict(po="PO master (PO Details)", grin="GRIN (GRIN Details)", payments="Payments (Payment Details)",
              notes="Debit / credit notes", balance="TAFE outstanding (Account Balance)", dqms="DQMS batch report")
MAX_TRIES = 3
MAX_PARTS = 8                        # a long master (notes, PO) may continue over this many calls
RETRY_AFTER = 600                    # seconds after a failure
STALE = 900                          # a 'running' row not updated for this long is treated as failed
BUDGET = 200                         # website: seconds of work per call (Vercel stops a function at 300 s)
_on = False
_local = threading.Lock()


def _now():
    return datetime.now().isoformat(timespec="seconds")


def enabled():
    v = str(os.environ.get("MASTERS_SYNC") or config.read_env().get("MASTERS_SYNC") or "1").strip().lower()
    return v not in ("0", "no", "off")


def slot_now(now=None):
    """'yyyy-mm-dd HH:MM' of the slot whose window we are in, or None."""
    now = now or datetime.now()
    for d in (now.date(), now.date() - timedelta(days=1)):
        for h, m in SLOTS:
            t = datetime(d.year, d.month, d.day, h, m)
            if t <= now <= t + timedelta(minutes=WINDOW_MIN):
                return t.strftime("%Y-%m-%d %H:%M")
    return None


def next_slot(now=None):
    now = now or datetime.now()
    for add in (0, 1):
        d = now.date() + timedelta(days=add)
        for h, m in SLOTS:
            t = datetime(d.year, d.month, d.day, h, m)
            if t > now:
                return t.strftime("%Y-%m-%d %H:%M")
    return None


# ---------------------------------------------------------------- the masters
def _wait(mod, started):
    """For the PC: modules that run in a thread - wait for the end."""
    if started:
        while mod.STATUS.get("running"):
            time.sleep(1)
    return dict(mod.STATUS)


def _status_result(st, rows_=0, message=""):
    err = st.get("error") or ""
    return dict(ok=not err, error=err, rows=rows_, message=message or (st.get("log") or [""])[-1][10:],
                more=bool(st.get("more")))


def run_po(ctx):
    from . import po_master
    slot = ctx.get("slot") or ""
    sunday_night = slot[:4].isdigit() and slot[11:13] == "21" and date.fromisoformat(slot[:10]).weekday() == 6
    full = bool(ctx.get("full") or sunday_night)
    years = 3 if full else 1
    res = po_master.fetch(years=years, budget=BUDGET if config.ON_VERCEL else None, done=ctx.get("done"),
                          log=ctx["log"])
    pub = res["published"]
    msg = (f"{res['rows']} PO lines read ({years} year{'s' if years > 1 else ''}): {res['pos_new']} new POs, "
           f"{res['lines_new']} new lines, {res['rate_changes']} rate changes; Supplementary Bill / DQMS: "
           f"{pub['parts_new']} parts added, {pub['parts_revised']} new rates")
    return dict(ok=True, rows=res["rows"], message=msg, more=res["more"], detail=dict(done=res["done"], years=years))


def run_grin(ctx):
    from ..supp.services import grin_portal as gp
    d2 = date.today()
    d1 = d2 - timedelta(days=45)
    st = _wait(gp, gp.start(d1, d2))
    import re
    lines = sum(int(m.group(1)) for x in st.get("log", []) for m in [re.search(r": (\d+) lines \(", x)] if m)
    return _status_result(st, lines)


def run_payments(ctx):
    from ..grin.services import pay_portal
    d2 = date.today()
    st = dict(pay_portal.run(d2 - timedelta(days=60), d2))
    return _status_result(st, (st.get("result") or {}).get("lines") or 0)


def run_notes(ctx):
    from ..grin.services import notes_portal
    d2 = date.today()
    st = dict(notes_portal.run(d2 - timedelta(days=45), d2, budget=BUDGET if config.ON_VERCEL else None))
    return _status_result(st, (st.get("result") or {}).get("documents") or 0)


def run_balance(ctx):
    from ..grin.services import balance_portal
    st = dict(balance_portal.run(ctx.get("source") or "8 am / 9 pm sync"))
    return _status_result(st, (st.get("result") or {}).get("lines") or 0)


def run_dqms(ctx):
    from ..dqms.services import dqms_portal
    problem = dqms_portal.why_not()
    if problem:
        return dict(ok=False, error=problem, rows=0, message="", more=False)
    dqms_portal.start()
    st = dict(dqms_portal.STATUS)
    return _status_result(st, (st.get("result") or {}).get("batches") or 0)


RUNNERS = dict(po=run_po, grin=run_grin, payments=run_payments, notes=run_notes, balance=run_balance, dqms=run_dqms)


# ---------------------------------------------------------------- sync_runs
def _claim(slot, master, try_no, trigger, detail=None):
    """Unique (slot, master, try): only one of website / PC gets it. -> run id or None."""
    token = uuid.uuid4().hex
    con = get_db()
    con.execute("INSERT OR IGNORE INTO sync_runs(slot, master, try_no, trigger, token, host, status, started, "
                "updated_ts, detail) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (slot, master, try_no, trigger, token, "website" if config.ON_VERCEL else socket.gethostname(),
                 "running", _now(), time.time(), json.dumps(detail or {})))
    con.commit()
    r = one("SELECT id, token FROM sync_runs WHERE slot=? AND master=? AND try_no=?", (slot, master, try_no))
    return r["id"] if r and r["token"] == token else None


def _finish(rid, res, log_lines):
    con = get_db()
    status = "partial" if res.get("ok") and res.get("more") else ("ok" if res.get("ok") else "error")
    detail = dict(res.get("detail") or {}, log=log_lines[-30:])
    con.execute("UPDATE sync_runs SET status=?, finished=?, updated_ts=?, rows=?, message=?, error=?, detail=? WHERE id=?",
                (status, _now(), time.time(), int(res.get("rows") or 0), (res.get("message") or "")[:500],
                 (res.get("error") or "")[:1000], json.dumps(detail), rid))
    con.commit()
    return status


def _execute(rid, master, ctx):
    lines = []

    def log(msg):
        lines.append(f"{datetime.now():%H:%M:%S}  {msg}")
        print(f"[Masters] {master}: {msg}")
        try:
            get_db().execute("UPDATE sync_runs SET updated_ts=? WHERE id=?", (time.time(), rid))
        except Exception:  # noqa: BLE001
            pass
    ctx["log"] = log
    try:
        res = RUNNERS[master](ctx)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        res = dict(ok=False, error=str(e), rows=0, message="", more=False)
    status = _finish(rid, res, lines)
    try:
        from ..db import log as activity
        activity("hub", f"master {master} {'refreshed' if status != 'error' else 'refresh failed'}",
                 (res.get("message") or res.get("error") or "")[:200], user=ctx.get("user") or ctx.get("trigger"))
    except Exception:  # noqa: BLE001
        pass
    return status


def tick(trigger="schedule", now=None):
    """Run the next master that is due in the current slot (one per call). -> what happened."""
    if not enabled():
        return dict(idle="MASTERS_SYNC is off")
    slot = slot_now(now)
    if not slot:
        return dict(idle=f"no slot now - next {next_slot(now)}")
    nowts = time.time()
    for master in ORDER:
        runs = rows("SELECT * FROM sync_runs WHERE slot=? AND master=? ORDER BY try_no", (slot, master))
        last = runs[-1] if runs else None
        if last and last["status"] == "running" and nowts - float(last["updated_ts"] or 0) > STALE:
            get_db().execute("UPDATE sync_runs SET status='error', error='stopped without finishing', finished=? "
                             "WHERE id=?", (_now(), last["id"]))
            get_db().commit()
            last = dict(last, status="error")
        if last and last["status"] in ("ok", "running"):
            continue
        if last and last["status"] == "error":
            fails = sum(1 for r in runs if r["status"] == "error")
            if fails >= MAX_TRIES or nowts - float(last["updated_ts"] or 0) < RETRY_AFTER:
                continue
        if last and last["status"] == "partial" and len(runs) >= MAX_PARTS:
            continue
        ctx = dict(slot=slot, trigger=trigger)
        if last and last["status"] == "partial":
            ctx["done"] = (json.loads(last["detail"] or "{}")).get("done")
        rid = _claim(slot, master, (last["try_no"] + 1) if last else 1, trigger)
        if not rid:
            continue
        status = _execute(rid, master, ctx)
        return dict(slot=slot, master=master, status=status)
    return dict(slot=slot, done=True)


def refresh(master, user="", full=False):
    """Refresh now (Masters page). Runs to the end (the website: up to the time limit, then says more)."""
    if master not in RUNNERS:
        raise ValueError(f"Unknown master {master}")
    with _local:
        busy = one("SELECT id FROM sync_runs WHERE master=? AND status='running' AND updated_ts>?",
                   (master, time.time() - STALE))
        if busy:
            raise RuntimeError(f"{LABELS[master]} is being refreshed right now - wait for it to finish")
        slot = "manual " + _now()
        rid = _claim(slot, master, 1, "manual")
    if not rid:
        raise RuntimeError("Could not start - press again")
    ctx = dict(slot=slot, trigger="manual", user=user, full=full)
    if config.ON_VERCEL:
        _execute(rid, master, ctx)
    else:
        threading.Thread(target=_execute, args=(rid, master, ctx), daemon=True).start()
    return one("SELECT * FROM sync_runs WHERE id=?", (rid,))


def overview():
    """Every master: last successful refresh, last run, row counts - for the Masters page."""
    from . import po_master
    out = []
    data_at = _data_times()
    for m in ORDER:
        last = one("SELECT * FROM sync_runs WHERE master=? ORDER BY id DESC LIMIT 1", (m,))
        ok = one("SELECT * FROM sync_runs WHERE master=? AND status IN ('ok','partial') ORDER BY id DESC LIMIT 1", (m,))
        good = max(filter(None, [ok and ok["finished"], data_at.get(m)]), default=None)
        age_h = (datetime.now() - datetime.fromisoformat(good)).total_seconds() / 3600 if good else None
        out.append(dict(master=m, label=LABELS[m], last=_clean(last), last_ok=good,
                        light="green" if age_h is not None and age_h <= 14 else "amber" if age_h is not None and age_h <= 26 else "red",
                        age_hours=round(age_h, 1) if age_h is not None else None,
                        running=bool(last and last["status"] == "running" and time.time() - float(last["updated_ts"] or 0) < STALE)))
    return dict(masters=out, slot=slot_now(), next=next_slot(), enabled=enabled(), po=po_master.summary(),
                history=[_clean(r) for r in rows("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 60")])


def _clean(r):
    if not r:
        return None
    r = dict(r)
    try:
        d = json.loads(r.pop("detail") or "{}")
    except ValueError:
        d = {}
    r["log"] = d.get("log") or []
    r.pop("token", None)
    return r


def _data_times():
    """When each master's data last arrived, also by the module buttons (Fetch GRIN, Fetch payments ...)."""
    out = {}
    q = lambda sql: ((one(sql) or {}).get("t"))  # noqa: E731
    for m, sql in (("po", "SELECT MAX(fetched_at) t FROM m_po"),
                   ("payments", "SELECT MAX(loaded_at) t FROM gp_pay_files"),
                   ("balance", "SELECT MAX(fetched_at) t FROM gp_bal_runs")):
        try:
            out[m] = q(sql)
        except Exception:  # noqa: BLE001
            pass
    try:
        from ..supp.services import grin_portal
        out["grin"] = grin_portal.fetched().get("at")
    except Exception:  # noqa: BLE001
        pass
    return {k: v for k, v in out.items() if v}


# ---------------------------------------------------------------- PC loop
def start_loop():
    """The SDEW PC hub: check every minute. With the shared cloud database the website does the same; the
    claim in sync_runs makes sure each master runs once per slot."""
    global _on
    if _on or config.ON_VERCEL or not enabled():
        return
    _on = True

    def loop():
        time.sleep(60)
        while True:
            try:
                r = tick("schedule (PC)")
                if r.get("master"):
                    continue                    # straight on to the next master of the slot
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            time.sleep(60)

    threading.Thread(target=loop, daemon=True, name="masters-sync").start()
    print("[Masters] TAFE Channel sync on: every day at 8:00 and 21:00 - " + ", ".join(ORDER))
