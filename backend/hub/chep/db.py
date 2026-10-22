"""The CHEP module's database.

PC (default): the hub's single database - settings keys get the prefix "chep.".
Cloud mode (Vercel, or USE_CLOUD_DB=1) with CHEP_TURSO_DATABASE_URL / CHEP_TURSO_AUTH_TOKEN set: the old
CHEP website's own Turso database (its live data), old table names and settings keys without prefix.
"""
import json
import threading

from .. import config
from .. import db as _db
from ..db import DatabaseUnavailable, migrate  # noqa: F401

MODULE = "chep"
PREFIX = "chep."


# A thread can be pointed at another CHEP database (the LEAP agent on the PC serves the website's
# database AND the old CHEP website's database). spec = (name, factory, prefixed); each thread opens
# its own connection from the factory.
_ovr = threading.local()


def use(spec):
    """Point this thread's CHEP code at spec (None = back to the normal database)."""
    _ovr.spec = spec


def current():
    return getattr(_ovr, "spec", None)


def get_db():
    spec = current()
    if spec is None:
        return _db.module_db(MODULE)
    name, factory, _ = spec
    cons = getattr(_ovr, "cons", None)
    if cons is None:
        cons = _ovr.cons = {}
    if name not in cons:
        cons[name] = factory()
    return cons[name]


def rows(sql, args=()):
    return [dict(r) for r in get_db().execute(sql, args).fetchall()]


def one(sql, args=()):
    r = get_db().execute(sql, args).fetchone()
    return dict(r) if r else None


def _key(key):
    spec = current()
    if spec is not None:
        return PREFIX + key if spec[2] else key
    return key if config.module_cloud_db(MODULE) else PREFIX + key


def get_setting(key, default=None):
    r = one("SELECT value FROM settings WHERE key=?", (_key(key),))
    return json.loads(r["value"]) if r else default


def set_setting(key, value):
    con = get_db()
    con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_key(key), json.dumps(value)))
    con.commit()
