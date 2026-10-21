"""SQLite access for the hub, plus read-only access to the copied legacy databases."""
import sqlite3
from . import config, seed

HUB_DB = config.DATA / "hub.db"


def connect():
    config.DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(HUB_DB), timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init():
    con = connect()
    con.executescript((config.ROOT / "core" / "schema.sql").read_text(encoding="utf-8"))
    seed.seed(con)
    con.close()


def rows(sql, args=()):
    con = connect()
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def execute(sql, args=()):
    con = connect()
    try:
        cur = con.execute(sql, args)
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def legacy_db_paths(app):
    base = config.LEGACY / app["folder"]
    return [base / p for p in app["dbs"] if (base / p).exists()]


def legacy_connect(path):
    """Open a copied legacy DB read-only so the hub never changes it."""
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con
