"""Phase 2 - do heavy work only when its data changed.

    versions(tables)                       the change counters of these tables (db.Tracked raises them on writes)
    cached(name, tables, fn, extra="")     fn()'s result, made again only when one of the tables changed
                                           (or 'extra' differs - e.g. today's date, the settings)

The result is kept in this server's memory and in the shared database (hub_cache, gzip + JSON), so another
website instance or the PC gets it with one row read instead of reading tens of thousands of rows.
Turso bills every row a query looks at; the GRIN Status list alone used to read about 100,000 rows per open.
"""
import base64
import gzip
import hashlib
import json
import threading
from datetime import datetime

from ..db import get_db, rows

_mem = {}
_lock = threading.Lock()


def versions(tables):
    tables = sorted({t.lower() for t in tables})
    q = ",".join("?" * len(tables))
    got = {r["t"]: r["ver"] for r in rows(f"SELECT t, ver FROM table_ver WHERE t IN ({q})", tuple(tables))}
    return ",".join(f"{t}:{got.get(t, 0)}" for t in tables)


def _sig(tables, extra):
    raw = versions(tables) + "|" + (extra if isinstance(extra, str) else json.dumps(extra, sort_keys=True, default=str))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def cached(name, tables, fn, extra=""):
    sig = _sig(tables, extra)
    with _lock:
        m = _mem.get(name)
        if m and m[0] == sig:
            return m[1]
    try:
        r = rows("SELECT sig, data FROM hub_cache WHERE name=?", (name,))
        if r and r[0]["sig"] == sig and r[0]["data"]:
            raw = r[0]["data"]
            raw = raw if isinstance(raw, (bytes, bytearray)) else base64.b64decode(raw)
            data = json.loads(gzip.decompress(raw).decode("utf-8"))
            with _lock:
                _mem[name] = (sig, data)
            return data
    except Exception as e:  # noqa: BLE001 - the cache never stops a page
        print(f"[cache] {name}: not read ({e})")
    data = fn()
    with _lock:
        _mem[name] = (sig, data)
    try:
        blob = gzip.compress(json.dumps(data, default=_plain).encode("utf-8"), 6)
        if len(blob) < 4_000_000:
            con = get_db()
            con.execute("INSERT INTO hub_cache(name, sig, data, at) VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
                        "sig=excluded.sig, data=excluded.data, at=excluded.at",
                        (name, sig, base64.b64encode(blob).decode("ascii"), datetime.now().isoformat(timespec="seconds")))
            con.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[cache] {name}: not saved ({e})")
    return data


def _plain(o):
    return sorted(o, key=str) if isinstance(o, (set, frozenset)) else str(o)


def clear(name=None):
    with _lock:
        if name:
            _mem.pop(name, None)
        else:
            _mem.clear()
