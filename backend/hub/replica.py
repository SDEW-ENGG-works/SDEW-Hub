"""Phase 3: the PC reads a local copy of the Turso database (an embedded replica) instead of Turso.

Only on the PC, and only with HUB_LOCAL_REPLICA=1 in .env (needs `pip install libsql`).
    - reads (SELECT / WITH) come from data\\turso_replica.db on the PC's disk: no Turso rows read;
    - every write still goes to Turso over HTTP (turso.Connection), exactly as before;
    - the copy is brought up to date (libsql sync: only the changed pages travel) when it is older
      than HUB_REPLICA_SYNC seconds (default 20), and after the PC's own writes, so the PC always
      reads what it wrote;
    - live tables the website and PC talk through (pc_jobs, pc_shots, sessions) are always read from
      Turso, so a button pressed on the website starts on the PC at once.
If libsql is missing, or the copy cannot be made or read, the hub silently uses Turso as before.
"""
import os
import re
import threading
import time

from . import config
from .turso import Row

LIVE = re.compile(r"\b(pc_jobs|pc_shots|sessions|logins)\b", re.I)
READ = re.compile(r"^\s*(SELECT|WITH)\b", re.I)
QUIET_AFTER_WRITE = 3.0        # seconds: while writes are coming, read from Turso; sync once they stop

_lock = threading.RLock()
_rep = None                    # the one shared libsql connection (guarded by _lock)
_state = dict(synced=0.0, wrote=0.0, dirty=False, failed=0.0, error="")


def enabled():
    if config.ON_VERCEL:
        return False
    v = str(os.environ.get("HUB_LOCAL_REPLICA") or config.read_env().get("HUB_LOCAL_REPLICA", "")).strip().lower()
    return v in ("1", "true", "yes", "on")


def _sync_every():
    try:
        return max(2.0, float(config.read_env().get("HUB_REPLICA_SYNC") or 20))
    except ValueError:
        return 20.0


def _open(url, token):
    global _rep
    if _rep is not None:
        return _rep
    if time.time() - _state["failed"] < 300:   # failed recently: do not retry on every request
        return None
    try:
        import libsql
        path = os.path.join(config.DATA_DIR, "turso_replica.db")
        con = libsql.connect(path, sync_url=url.strip(), auth_token=token.strip())
        con.sync()
        _rep = con
        _state.update(synced=time.time(), dirty=False, error="")
        print("Local Turso copy ready:", path)
    except Exception as e:  # noqa: BLE001
        _state.update(failed=time.time(), error=str(e))
        print("Local Turso copy not used (reading Turso directly):", e)
    return _rep


def info():
    return dict(enabled=enabled(), ready=_rep is not None, synced=_state["synced"], error=_state["error"])


class _Rows:
    """A cursor over rows already read (dict rows, like turso.Cursor)."""

    def __init__(self, rows):
        self._rows = rows
        self.lastrowid, self.rowcount = None, -1

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class Hybrid:
    """Turso connection whose reads come from the local copy when it is safe to."""

    def __init__(self, remote, rep):
        self.remote, self.rep = remote, rep

    def _local_ok(self, sql):
        if not READ.match(sql) or LIVE.search(sql) or getattr(self.remote, "_queue", None):
            return False
        now = time.time()
        if _state["dirty"] and now - _state["wrote"] < QUIET_AFTER_WRITE:
            return False
        if _state["dirty"] or now - _state["synced"] > _sync_every():
            try:
                self.rep.sync()
                _state.update(synced=time.time(), dirty=False)
            except Exception as e:  # noqa: BLE001
                _state["error"] = f"sync: {e}"
                return False
        return True

    def execute(self, sql, args=()):
        with _lock:
            if self._local_ok(sql):
                try:
                    cur = self.rep.execute(sql, tuple(args or ()))
                    names = [d[0] for d in (cur.description or [])]
                    return _Rows([Row(zip(names, r)) for r in cur.fetchall()])
                except Exception:  # noqa: BLE001 - e.g. a table made after the last sync: ask Turso
                    pass
        if not READ.match(sql):
            self._wrote()
        return self.remote.execute(sql, args)

    def _wrote(self):
        _state.update(dirty=True, wrote=time.time())

    def executemany(self, sql, seq):
        self._wrote()
        return self.remote.executemany(sql, seq)

    def executescript(self, script):
        self._wrote()
        return self.remote.executescript(script)

    def commit(self):
        if getattr(self.remote, "_queue", None):
            self._wrote()
        out = self.remote.commit()
        if _state["dirty"]:
            _state["wrote"] = time.time()
        return out

    def __getattr__(self, name):
        return getattr(self.remote, name)


def wrap(remote, url, token):
    """The remote connection itself, or a Hybrid when the local copy is on and works."""
    if not enabled():
        return remote
    with _lock:
        rep = _open(url, token)
    return Hybrid(remote, rep) if rep is not None else remote
