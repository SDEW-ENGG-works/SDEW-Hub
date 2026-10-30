"""Backups of the whole hub database, made on the SDEW PC.

  Every night  the hub on the PC copies EVERY table of the database it uses (the Turso cloud database, or
               data\\sdew_hub.db) into one file: data\\backups\\sdew_hub_<date>_<time>_<reason>.zip
               (inside: sdew_hub.db + manifest.json with the row counts). Default after 21:00; a PC that was
               off at night does it as soon as the hub starts again.
  Copy         BACKUP_COPY_DIR in .env (e.g. a Google Drive folder: G:\\My Drive\\SDEW Hub backups) gets a copy
               of every backup, so a backup survives a broken PC.
  Keep         30 days (BACKUP_KEEP_DAYS), in both places.
  Restore      Admin page > Backups > Restore: a backup of NOW is made first ("before restore"), then every
               table is emptied and filled from the chosen backup. Logins (users), the backup list and the
               activity list are kept as they are.
  The website cannot write files, so its Back up now / Restore buttons are jobs for the PC (services/pc_jobs).
"""
import json
import os
import shutil
import socket
import sqlite3
import tempfile
import threading
import time
import traceback
import zipfile
from datetime import datetime, timedelta

from .. import config
from ..db import CURRENT_USER, get_db, log, one, rows, set_setting, get_setting

PAGE = 2000                # rows read per query
BATCH = 400                # rows written per commit when restoring
KEEP_TABLES = {"backups", "activity", "users", "login_fails", "pc_jobs", "sqlite_sequence", "wipe_snapshots", "wipe_rows"}   # never overwritten
STATUS = dict(running=False, log=[], started="", finished="", error="", result=None)
_lock = threading.Lock()


def _log(msg):
    STATUS["log"].append(f"{datetime.now():%H:%M:%S}  {msg}")
    STATUS["log"] = STATUS["log"][-80:]
    print("[Backup]", msg)


def backup_dir():
    d = os.path.join(config.DATA_DIR, "backups")
    os.makedirs(d, exist_ok=True)
    return d


def copy_dir():
    return (config.read_env().get("BACKUP_COPY_DIR") or "").strip()


def keep_days():
    try:
        return max(1, int(config.read_env().get("BACKUP_KEEP_DAYS") or 30))
    except ValueError:
        return 30


def nightly_hour():
    try:
        return min(23, max(0, int(config.read_env().get("BACKUP_HOUR") or 21)))
    except ValueError:
        return 21


# ------------------------------------------------------------------ make
def _tables(src):
    out = []
    for r in src.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                         "AND name NOT LIKE '_litestream%' AND name NOT LIKE 'libsql_%' ORDER BY name").fetchall():
        out.append((r["name"], r["sql"]))
    return out


def make(reason="manual", user=None):
    """Copies every table into a new backup file. -> dict(name, size, tables, copy)."""
    src = get_db()
    stamp = datetime.now()
    name = f"sdew_hub_{stamp:%Y%m%d_%H%M%S}_{reason}.zip"
    tmpd = tempfile.mkdtemp(prefix="hubbk_")
    dbp = os.path.join(tmpd, "sdew_hub.db")
    out = sqlite3.connect(dbp)
    counts = {}
    try:
        for t, sql in _tables(src):
            out.execute(sql)
            cols = [r[1] for r in src.execute(f"PRAGMA table_info({t})").fetchall()]
            qcols = ", ".join(f'"{c}"' for c in cols)
            ins = f'INSERT INTO "{t}"({qcols}) VALUES({", ".join("?" * len(cols))})'
            n, last = 0, None
            while True:      # page through by rowid: a big table never comes back in one answer
                if last is None:
                    batch = src.execute(f'SELECT rowid AS __r, {qcols} FROM "{t}" ORDER BY rowid LIMIT {PAGE}').fetchall()
                else:
                    batch = src.execute(f'SELECT rowid AS __r, {qcols} FROM "{t}" WHERE rowid > ? ORDER BY rowid '
                                        f'LIMIT {PAGE}', (last,)).fetchall()
                if not batch:
                    break
                out.executemany(ins, [tuple(r[c] for c in cols) for r in batch])
                n += len(batch)
                last = batch[-1]["__r"]
                if len(batch) < PAGE:
                    break
            counts[t] = n
            _log(f"{t}: {n} rows")
        out.commit()
        out.close()
        manifest = dict(name=name, at=stamp.isoformat(timespec="seconds"), reason=reason,
                        user=CURRENT_USER.get() if user is None else user, host=socket.gethostname(),
                        source=config.db_mode(), tables=counts)
        path = os.path.join(backup_dir(), name)
        with zipfile.ZipFile(path + ".part", "w", zipfile.ZIP_DEFLATED) as z:
            z.write(dbp, "sdew_hub.db")
            z.writestr("manifest.json", json.dumps(manifest, indent=1))
        os.replace(path + ".part", path)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
    size = os.path.getsize(path)
    copied = ""
    cd = copy_dir()
    if cd:
        try:
            os.makedirs(cd, exist_ok=True)
            shutil.copy2(path, os.path.join(cd, name))
            copied = cd
            _log(f"Copy saved in {cd}")
        except OSError as e:
            copied = f"FAILED: {e}"
            _log(f"Copy to {cd} failed: {e}")
    con = get_db()
    con.execute("INSERT OR REPLACE INTO backups(name, at, reason, user, host, size, tables, copy, gone) "
                "VALUES(?,?,?,?,?,?,?,?,0)", (name, manifest["at"], reason, manifest["user"], manifest["host"], size,
                                               json.dumps(counts), copied))
    con.commit()
    log("hub", "backup made", f"{name} ({size // 1024} KB, {sum(counts.values())} rows)"
        + (f", copy in {copied}" if copied and not copied.startswith("FAILED") else ""),
        user=manifest["user"])
    prune()
    return dict(name=name, size=size, tables=counts, copy=copied)


def prune():
    """Backups older than keep_days() go - in data\\backups and in the copy folder."""
    cutoff = (datetime.now() - timedelta(days=keep_days())).strftime("%Y%m%d")
    gone = []
    for d in filter(None, [backup_dir(), copy_dir()]):
        try:
            for f in os.listdir(d):
                if f.startswith("sdew_hub_") and f.endswith(".zip") and f[9:17].isdigit() and f[9:17] < cutoff:
                    try:
                        os.remove(os.path.join(d, f))
                        gone.append(f)
                    except OSError:
                        pass
        except OSError:
            pass
    if gone:
        con = get_db()
        for f in set(gone):
            con.execute("UPDATE backups SET gone=1 WHERE name=?", (f,))
        con.commit()


def listing():
    """Backups known to the database, newest first, with 'here' = the file is on this computer."""
    out = rows("SELECT id, name, at, reason, user, host, size, tables, copy, gone FROM backups ORDER BY at DESC LIMIT 200")
    local = set(os.listdir(backup_dir())) if not config.ON_VERCEL else set()
    for r in out:
        t = json.loads(r.pop("tables") or "{}")
        r["rows"] = sum(t.values())
        r["here"] = r["name"] in local
    return out


def _find(name):
    for d in filter(None, [backup_dir(), copy_dir()]):
        p = os.path.join(d, os.path.basename(name))
        if os.path.exists(p):
            return p
    return None


# ------------------------------------------------------------------ restore
def restore(name, user=None):
    """Puts the whole database back to a backup. A backup of now is made first."""
    path = _find(name)
    if not path:
        raise FileNotFoundError(f"{name} is not in data\\backups (or the copy folder) on this PC")
    _log("First a backup of the data as it is now")
    before = make("before-restore", user=user)
    tmpd = tempfile.mkdtemp(prefix="hubrs_")
    try:
        with zipfile.ZipFile(path) as z:
            z.extract("sdew_hub.db", tmpd)
        src = sqlite3.connect(os.path.join(tmpd, "sdew_hub.db"))
        src.row_factory = sqlite3.Row
        dst = get_db()
        live = {r["name"] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        total = 0
        for t, _sql in _tables(src):
            if t in KEEP_TABLES or t not in live:
                continue
            have = {r[1] for r in dst.execute(f"PRAGMA table_info({t})").fetchall()}
            cols = [r[1] for r in src.execute(f'PRAGMA table_info("{t}")').fetchall() if r[1] in have]
            data = src.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{t}"').fetchall()
            dst.execute(f"DELETE FROM {t}")
            sql = f'INSERT INTO {t}({", ".join(cols)}) VALUES({", ".join("?" * len(cols))})'
            for i in range(0, len(data), BATCH):
                for r in data[i:i + BATCH]:
                    dst.execute(sql, tuple(r))
                dst.commit()
            dst.commit()
            total += len(data)
            _log(f"{t}: {len(data)} rows put back")
        src.close()
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
    log("hub", "backup restored", f"{name} ({total} rows); the data from before is in {before['name']}", user=user)
    return dict(name=name, rows=total, before=before["name"])


# ------------------------------------------------------------------ jobs (button on the page / the PC agent)
def start(kind, params=None, user=None):
    """kind 'backup' or 'restore' in a thread; progress in STATUS (same shape as the other PC jobs)."""
    with _lock:
        if STATUS["running"]:
            return False
        STATUS.update(running=True, log=[], started=datetime.now().isoformat(timespec="seconds"), finished="",
                      error="", result=None)
    threading.Thread(target=_run, args=(kind, params or {}, user), daemon=True).start()
    return True


def _run(kind, params, user):
    try:
        if kind == "restore":
            STATUS["result"] = restore(params.get("name", ""), user=user)
        else:
            STATUS["result"] = make(params.get("reason") or "manual", user=user)
        _log("Done")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        STATUS["error"] = str(e)
        _log(f"Stopped: {e}")
    finally:
        STATUS["running"] = False
        STATUS["finished"] = datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------ nightly, on the PC
_night_on = False


def due(now=None):
    now = now or datetime.now()
    last = (get_setting("hub.last_nightly_backup") or "")
    if not last:
        return True
    try:
        lt = datetime.fromisoformat(last)
    except ValueError:
        return True
    if now - lt > timedelta(hours=36):          # the PC was off at night: do it now
        return True
    return now.hour >= nightly_hour() and lt.date() < now.date()


def start_nightly():
    """Started by the PC's server (never on Vercel). Looks every 10 minutes whether tonight's backup is due."""
    global _night_on
    if _night_on or config.ON_VERCEL or str(config.read_env().get("BACKUP_NIGHTLY", "1")).strip() in ("0", "no", "off"):
        return
    _night_on = True

    def loop():
        time.sleep(60)
        while True:
            try:
                go = False
                if due():
                    with _lock:
                        if not STATUS["running"]:
                            STATUS.update(running=True, log=[], started=datetime.now().isoformat(timespec="seconds"),
                                          finished="", error="", result=None)
                            go = True
                if go:
                    try:
                        STATUS["result"] = make("nightly", user="nightly (PC)")
                        set_setting("hub.last_nightly_backup", datetime.now().isoformat(timespec="seconds"))
                    except Exception as e:  # noqa: BLE001
                        traceback.print_exc()
                        STATUS["error"] = str(e)
                        log("hub", "nightly backup FAILED", str(e)[:300], user="nightly (PC)")
                    finally:
                        STATUS["running"] = False
                        STATUS["finished"] = datetime.now().isoformat(timespec="seconds")
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            time.sleep(600)

    threading.Thread(target=loop, daemon=True, name="nightly-backup").start()
    print(f"[Backup] nightly backup on (after {nightly_hour()}:00, kept {keep_days()} days"
          + (f", copy to {copy_dir()}" if copy_dir() else "") + ")")


def info():
    last = one("SELECT name, at, size, copy FROM backups WHERE reason='nightly' ORDER BY at DESC LIMIT 1")
    return dict(dir=None if config.ON_VERCEL else backup_dir(), copy_dir=copy_dir(), keep_days=keep_days(),
                hour=nightly_hour(), last_nightly=last, status=dict(STATUS))
