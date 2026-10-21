"""The DQMS module's database.

PC (default): the hub's single database - settings keys get the prefix "dqms.".
Cloud mode (Vercel, or USE_CLOUD_DB=1) with DQMS_TURSO_DATABASE_URL / DQMS_TURSO_AUTH_TOKEN set: the old
DQMS website's own Turso database (its live data), old table names and settings keys without prefix.
"""
import json

from .. import config
from .. import db as _db
from ..db import DatabaseUnavailable, migrate  # noqa: F401

MODULE = "dqms"
PREFIX = "dqms."


def get_db():
    return _db.module_db(MODULE)


def rows(sql, args=()):
    return [dict(r) for r in get_db().execute(sql, args).fetchall()]


def one(sql, args=()):
    r = get_db().execute(sql, args).fetchone()
    return dict(r) if r else None


def _key(key):
    return key if config.module_cloud_db(MODULE) else PREFIX + key


def get_setting(key, default=None):
    r = one("SELECT value FROM settings WHERE key=?", (_key(key),))
    return json.loads(r["value"]) if r else default


def set_setting(key, value):
    con = get_db()
    con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_key(key), json.dumps(value)))
    con.commit()
