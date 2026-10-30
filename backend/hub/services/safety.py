"""Safety nets that work the same on the PC and on the website.

  Login lockout       5 wrong passwords for one username -> that username is locked for 15 minutes
  Clear data          the "clear data" buttons are for the admin only, and the rows are copied into
                      wipe_snapshots / wipe_rows FIRST - the Admin page can put them back (Undo)
  Who did what        http.dispatch notes every change (upload, file made, setting saved, delete) in the
                      activity list with the user's name - see audit()
"""
import base64
import json
import time
from datetime import datetime

from ..db import CURRENT_USER, get_db, log, one, rows

MAX_FAILS = 5
LOCK_MINUTES = 15
WINDOW_MINUTES = 15          # wrong passwords further apart than this start counting again
CHUNK = 200                  # rows per wipe_rows record


def _now():
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------ login lockout
def _key(username):
    return (username or "").strip().lower() or "(shared password)"


def locked_until(username):
    """Epoch seconds until which this username is locked, or 0."""
    try:
        r = one("SELECT locked_until FROM login_fails WHERE key=?", (_key(username),))
    except Exception:  # noqa: BLE001
        return 0
    t = float((r or {}).get("locked_until") or 0)
    return t if t > time.time() else 0


def login_failed(username):
    """Counts a wrong password. -> epoch seconds of the lock when this attempt locked the username, else 0."""
    k, now = _key(username), time.time()
    try:
        con = get_db()
        r = one("SELECT n, first_at, locked_until FROM login_fails WHERE key=?", (k,))
        n, first = (r["n"] or 0, float(r["first_at"] or now)) if r else (0, now)
        if now - first > WINDOW_MINUTES * 60 or float((r or {}).get("locked_until") or 0) and \
                float(r["locked_until"]) <= now:
            n, first = 0, now                       # old mistakes / an ended lock: start again
        n += 1
        until = now + LOCK_MINUTES * 60 if n >= MAX_FAILS else 0
        con.execute("INSERT INTO login_fails(key, n, first_at, locked_until, last_at) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET n=excluded.n, first_at=excluded.first_at, "
                    "locked_until=excluded.locked_until, last_at=excluded.last_at", (k, n, first, until, _now()))
        con.commit()
        log("hub", "login failed" + (" - locked for 15 minutes" if until else ""),
            f"username '{(username or '').strip() or '(none)'}', wrong password {n} of {MAX_FAILS}", user="")
        return until
    except Exception:  # noqa: BLE001 - the database being down must not open the door
        return 0


def login_ok(username):
    try:
        con = get_db()
        con.execute("DELETE FROM login_fails WHERE key=?", (_key(username),))
        con.commit()
    except Exception:  # noqa: BLE001
        pass


def locked_list():
    now = time.time()
    out = []
    for r in rows("SELECT key, n, locked_until, last_at FROM login_fails"):
        if float(r["locked_until"] or 0) > now:
            out.append(dict(username=r["key"], until=datetime.fromtimestamp(float(r["locked_until"]))
                            .isoformat(timespec="seconds"), fails=r["n"]))
    return out


def unlock(username):
    login_ok(username)
    log("hub", "login unlocked", f"username '{username}'")


# ------------------------------------------------------------------ clear data: copy first, then delete
def _enc(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"b64": base64.b64encode(bytes(v)).decode("ascii")}
    return v


def _dec(v):
    if isinstance(v, dict) and "b64" in v:
        return base64.b64decode(v["b64"])
    return v


def before_wipe(module, what, tables, con, extra_settings=()):
    """Copies every row of `tables` (read through `con`, the module's own connection) into wipe_snapshots /
    wipe_rows of the hub database. -> snapshot id. Raises if the copy fails - then nothing is deleted."""
    hub = get_db()
    cur = hub.execute("INSERT INTO wipe_snapshots(at, user, module, what, tables, rows) VALUES(?,?,?,?,?,?)",
                      (_now(), CURRENT_USER.get() or "", module, what, json.dumps(list(tables)), 0))
    sid = cur.lastrowid
    if sid is None:
        sid = one("SELECT MAX(id) id FROM wipe_snapshots")["id"]
    total = 0
    for t in tables:
        data = [dict(r) for r in con.execute(f"SELECT * FROM {t}").fetchall()]
        for i in range(0, len(data), CHUNK):
            part = [{k: _enc(v) for k, v in r.items()} for r in data[i:i + CHUNK]]
            hub.execute("INSERT INTO wipe_rows(snap_id, tbl, seq, data) VALUES(?,?,?,?)",
                        (sid, t, i // CHUNK, json.dumps(part)))
        total += len(data)
    for i, key in enumerate(extra_settings):
        r = con.execute("SELECT key, value FROM settings WHERE key=?", (key,)).fetchone()
        if r:
            hub.execute("INSERT INTO wipe_rows(snap_id, tbl, seq, data) VALUES(?,?,?,?)",
                        (sid, "settings", i, json.dumps([dict(r)])))
    hub.execute("UPDATE wipe_snapshots SET rows=? WHERE id=?", (total, sid))
    hub.commit()
    log(module, "data cleared", f"{what}: {total} rows from {', '.join(tables)} (copy kept: Admin > Cleared data > Put back, #{sid})")
    return sid


def snapshots():
    return rows("SELECT id, at, user, module, what, tables, rows, restored_at, restored_by FROM wipe_snapshots "
                "ORDER BY id DESC LIMIT 100")


def restore_snapshot(sid, con_for):
    """Puts the rows of a snapshot back (rows still there are kept - INSERT OR IGNORE).
    con_for(module) -> the connection that module's tables live in."""
    s = one("SELECT * FROM wipe_snapshots WHERE id=?", (sid,))
    if not s:
        raise ValueError("Snapshot not found")
    con = con_for(s["module"])
    n = 0
    for part in rows("SELECT tbl, data FROM wipe_rows WHERE snap_id=? ORDER BY tbl, seq", (sid,)):
        data = json.loads(part["data"])
        if not data:
            continue
        have = {r[1] for r in con.execute(f"PRAGMA table_info({part['tbl']})").fetchall()}
        cols = [c for c in data[0] if c in have]
        sql = (f"INSERT OR {'REPLACE' if part['tbl'] == 'settings' else 'IGNORE'} INTO {part['tbl']}"
               f"({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})")
        for r in data:
            con.execute(sql, tuple(_dec(r.get(c)) for c in cols))
            n += 1
        con.commit()
    hub = get_db()
    hub.execute("UPDATE wipe_snapshots SET restored_at=?, restored_by=? WHERE id=?", (_now(), CURRENT_USER.get(), sid))
    hub.commit()
    log(s["module"], "cleared data put back", f"#{sid} {s['what']}: {n} rows")
    return n


# ------------------------------------------------------------------ who did what
SKIP = ("/preview", "/api/login", "/api/logout", "/tally/plan", "/tally/ingest", "/tally/test",
        "/leap/decide", "/batches/clear", "/api/pay/refresh")
WORDS = {
    "upload": "uploaded", "bill/run": "calculated the bill", "generate": "made a file", "combine": "combined files",
    "settings/reset-data": "cleared data", "settings": "saved settings", "template": "uploaded a template",
    "grin/sync": "started Fetch GRIN", "tally/pull": "started Pull from Tally", "payments/fetch": "started Fetch payments",
    "dqms/fetch": "started Get DQMS report", "leap/start": "started LEAP upload", "leap/cancel": "cancelled LEAP upload",
    "mails/send": "sent reminder mails", "buyers": "saved a buyer", "note": "saved a note", "parts": "changed a part size",
    "pos/line": "typed a PO line item", "invoices/edits": "edited an invoice", "invoices/delete": "removed an invoice",
    "check": "ran the check", "category": "ticked a category", "lines": "ticked a line", "open-items": "follow-up",
    "notes/fetch": "started Fetch notes", "reread": "re-read a packing list", "pos": "changed a PO",
    "runs": "deleted a History file", "users": "changed a login", "backup": "backup", "restore": "restore",
}


def audit(req, resp):
    """Called by http.dispatch after every request: a change that worked and was not logged by the handler
    itself gets one activity line (module, what, the file name / number, who)."""
    if req.method == "GET" or resp.status >= 400 or any(x in req.path for x in SKIP):
        return
    parts = req.path.split("/")[2:]                     # ['supp', 'bill', 'run']
    if not parts:
        return
    mod = parts[0] if parts[0] in ("supp", "chep", "dqms", "grin", "pay") else "hub"
    rest = "/".join(p for p in parts[1:] if not p.isdigit()) if mod != "hub" else "/".join(
        p for p in parts[1:] if not p.isdigit())
    action = None
    for k in sorted(WORDS, key=len, reverse=True):
        if rest.endswith(k) or rest == k:
            action = WORDS[k]
            break
    if action is None:
        action = rest.replace("/", " ") or req.method.lower()
    if req.method == "DELETE" and not action.startswith("deleted"):
        action = "deleted: " + action
    detail = []
    nm = req.arg("name")
    if nm:
        detail.append(nm)
    ids = [p for p in parts if p.isdigit()]
    if ids:
        detail.append("#" + ids[0])
    try:
        b = req.json if req._body_bytes and req._body_bytes[:1] == b"{" else {}
    except Exception:  # noqa: BLE001
        b = {}
    for k in ("what", "po_no", "part", "inv_no", "title", "status", "username"):
        if isinstance(b, dict) and b.get(k) not in (None, "") and not isinstance(b.get(k), (dict, list)):
            detail.append(f"{k} {str(b[k])[:60]}")
    log(mod, action, ", ".join(detail))
