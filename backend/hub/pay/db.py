"""The hub's single database, seen from this module. Settings keys get the prefix "pay."."""
from .. import db as _db
from ..db import DatabaseUnavailable, get_db, log, one, rows  # noqa: F401

PREFIX = "pay."


def get_setting(key, default=None):
    return _db.get_setting(PREFIX + key, default)


def set_setting(key, value):
    _db.set_setting(PREFIX + key, value)
