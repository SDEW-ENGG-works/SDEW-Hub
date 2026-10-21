"""One database for every module: data/sdew_hub.db on the PC, or the Turso cloud database
(USE_CLOUD_DB=1 on the PC, or on Vercel). Nothing to install.

Shared tables (used by more than one module):
  settings      key/value; each module's keys start with its name ("supp.app", "chep.app", ...)
  po_headers    TAFE purchase orders - Supplementary Bill prices AND DQMS line items read the same rows
  po_items      one row per PO + part: line item, description, rate, date-wise price blocks
Module tables keep the names they had in the old apps, except the three "runs" tables
(bill_runs / chep_runs / dqms_runs).
"""
import json
import sqlite3
import threading

from . import config


class DatabaseUnavailable(Exception):
    pass


_local = threading.local()
_init_lock = threading.Lock()
_ready = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);

-- ---------- shared: TAFE purchase orders ----------
CREATE TABLE IF NOT EXISTS po_headers(
    po_no TEXT PRIMARY KEY, plant TEXT, po_date TEXT, valid_till TEXT, bill_to TEXT,
    items INTEGER, file_id INTEGER, uploaded_at TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS po_items(
    po_no TEXT, part TEXT, item INTEGER, descr TEXT, uom TEXT, rate REAL, blocks TEXT,
    PRIMARY KEY(po_no, part));
CREATE INDEX IF NOT EXISTS ix_po_items_part ON po_items(part);

-- ---------- Supplementary Bill ----------
CREATE TABLE IF NOT EXISTS files(
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, name TEXT, stored TEXT,
    uploaded_at TEXT, rows INTEGER, info TEXT);
CREATE TABLE IF NOT EXISTS grin_lines(
    grin_no TEXT, line_no TEXT, grin_date TEXT, invoice_no TEXT, invoice_date TEXT,
    plant TEXT, po_no TEXT, po_date TEXT, part_no TEXT, part_desc TEXT,
    grin_qty REAL, accepted_qty REAL, rejected_qty REAL, part_rate REAL, freight REAL,
    source TEXT, source_file TEXT, updated_at TEXT,
    PRIMARY KEY(grin_no, line_no));
CREATE TABLE IF NOT EXISTS sales_lines(
    voucher TEXT, part TEXT, seq INTEGER, inv_date TEXT, party TEXT, order_no TEXT,
    order_due TEXT, item_name TEXT, descr TEXT, hsn TEXT, gst REAL, qty REAL, rate REAL,
    file_id INTEGER, PRIMARY KEY(voucher, part, seq));
CREATE TABLE IF NOT EXISTS grn_sheet(
    voucher TEXT, part TEXT, seq INTEGER, grn_no TEXT, grn_date TEXT, qty REAL, file_id INTEGER,
    PRIMARY KEY(voucher, part, seq));
CREATE TABLE IF NOT EXISTS bill_runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, params TEXT, summary TEXT);
CREATE TABLE IF NOT EXISTS run_lines(
    run_id INTEGER, plant TEXT, cat TEXT, reason TEXT, voucher TEXT, inv_date TEXT, party TEXT,
    order_no TEXT, po_no TEXT, order_due TEXT, part TEXT, descr TEXT, hsn TEXT, gst REAL, qty REAL,
    rate REAL, old_rate REAL, new_rate REAL, diff REAL, value REAL, grn_no TEXT, grn_date TEXT,
    status TEXT, notes TEXT, old_src TEXT);
CREATE INDEX IF NOT EXISTS ix_run_lines ON run_lines(run_id, plant, cat);
CREATE INDEX IF NOT EXISTS ix_run_lines_voucher ON run_lines(voucher);
CREATE INDEX IF NOT EXISTS ix_grin_inv ON grin_lines(invoice_no);
CREATE INDEX IF NOT EXISTS ix_sales_part ON sales_lines(part);

-- ---------- CHEP Transfer ----------
CREATE TABLE IF NOT EXISTS batches(
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, stored TEXT, uploaded_at TEXT, parsed TEXT, data BLOB);
CREATE TABLE IF NOT EXISTS chep_runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER, created_at TEXT, file_name TEXT,
    doc_date TEXT, summary TEXT, rows TEXT, xlsx BLOB, leap_status TEXT, leap_result TEXT, leap_at TEXT);
CREATE TABLE IF NOT EXISTS part_types(
    part TEXT PRIMARY KEY, type TEXT, part_name TEXT, source TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS templates(
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, uploaded_at TEXT, data BLOB);
CREATE TABLE IF NOT EXISTS leap_jobs(
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, mode TEXT, headed INTEGER, status TEXT,
    state TEXT, decision TEXT, created_at TEXT, updated_ts REAL);

-- ---------- DQMS Upload ----------
CREATE TABLE IF NOT EXISTS invoices(
    inv_no TEXT PRIMARY KEY, inv_date TEXT, order_no TEXT, total REAL, cgst REAL, sgst REAL, igst REAL,
    packages INTEGER, drs TEXT, items TEXT, consignee TEXT, warnings TEXT, edits TEXT,
    file_name TEXT, uploaded_at TEXT, run_id INTEGER, eway TEXT);
CREATE TABLE IF NOT EXISTS dqms_batches(
    batch_no TEXT PRIMARY KEY, part TEXT, descr TEXT, total REAL, consumed REAL, balance REAL, created TEXT);
CREATE TABLE IF NOT EXISTS line_overrides(
    po_no TEXT, part TEXT, item INTEGER, updated_at TEXT, PRIMARY KEY(po_no, part));
CREATE TABLE IF NOT EXISTS portal_status(
    inv_no TEXT, seq INTEGER, record TEXT, part TEXT, batch_no TEXT, status TEXT, message TEXT,
    file_name TEXT, uploaded_at TEXT, PRIMARY KEY(inv_no, seq));
CREATE TABLE IF NOT EXISTS dqms_runs(
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, file_name TEXT, summary TEXT, rows TEXT,
    invoices TEXT, csv BLOB);
CREATE TABLE IF NOT EXISTS delivery_requests(
    dr_no TEXT, part TEXT, order_no TEXT, descr TEXT, bin TEXT, req INTEGER, size REAL, qty REAL,
    file_name TEXT, uploaded_at TEXT, PRIMARY KEY(dr_no, part));

-- ---------- GRIN & Payments ----------
CREATE TABLE IF NOT EXISTS gp_tally_invoices(
    inv_key TEXT PRIMARY KEY, inv_no TEXT, inv_date TEXT, party TEXT, company TEXT, amount REAL, order_no TEXT,
    cancelled INTEGER DEFAULT 0, source TEXT, pulled_at TEXT);
CREATE TABLE IF NOT EXISTS gp_tally_lines(
    inv_key TEXT, seq INTEGER, part TEXT, item_name TEXT, qty REAL, rate REAL, amount REAL, order_no TEXT,
    PRIMARY KEY(inv_key, seq));
CREATE TABLE IF NOT EXISTS gp_register(
    inv_key TEXT PRIMARY KEY, inv_no TEXT, inv_date TEXT, amount REAL, party TEXT, pv TEXT, pv_date TEXT,
    cancelled INTEGER DEFAULT 0, file TEXT, loaded_at TEXT);
CREATE TABLE IF NOT EXISTS gp_pay_lines(
    pv TEXT, pv_date TEXT, ref_doc TEXT, doc_type TEXT, inv_raw TEXT, inv_key TEXT, inv_date TEXT,
    debit REAL, credit REAL, file TEXT, loaded_at TEXT, PRIMARY KEY(pv, ref_doc, inv_key));
CREATE INDEX IF NOT EXISTS ix_gp_pay_inv ON gp_pay_lines(inv_key);
CREATE TABLE IF NOT EXISTS gp_pay_files(
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, name TEXT, stored TEXT, period_from TEXT, period_to TEXT,
    rows INTEGER, loaded_at TEXT);
CREATE TABLE IF NOT EXISTS gp_buyers(
    id INTEGER PRIMARY KEY AUTOINCREMENT, plant TEXT, po_no TEXT, name TEXT, email TEXT, cc TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS gp_mails(
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, sent_at TEXT, buyer_id INTEGER, buyer TEXT,
    to_addr TEXT, cc TEXT, subject TEXT, body TEXT, invoices TEXT, status TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS gp_mail_invoices(
    mail_id INTEGER, inv_key TEXT, sent_at TEXT, PRIMARY KEY(mail_id, inv_key));
CREATE INDEX IF NOT EXISTS ix_gp_mail_inv ON gp_mail_invoices(inv_key);
CREATE TABLE IF NOT EXISTS gp_notes(
    inv_key TEXT PRIMARY KEY, note TEXT, hold INTEGER DEFAULT 0, updated_at TEXT);

-- ---------- Jobs the website hands to the SDEW PC (Tally pull, Fetch GRIN) ----------
CREATE TABLE IF NOT EXISTS pc_jobs(
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, params TEXT, status TEXT, log TEXT, error TEXT,
    result TEXT, created_at TEXT, started_at TEXT, finished_at TEXT, host TEXT, updated_ts REAL);

-- ---------- Hub ----------
CREATE TABLE IF NOT EXISTS open_items(
    id INTEGER PRIMARY KEY AUTOINCREMENT, module TEXT, title TEXT, detail TEXT,
    status TEXT DEFAULT 'open', created_at TEXT, done_at TEXT);
CREATE TABLE IF NOT EXISTS activity(
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, module TEXT, action TEXT, detail TEXT);
"""

# columns added after the first version: (table, column, type)
MIGRATIONS = [
    ("po_headers", "source", "TEXT"),
    ("run_lines", "old_src", "TEXT"),
    ("batches", "data", "BLOB"),
    ("chep_runs", "leap_status", "TEXT"), ("chep_runs", "leap_result", "TEXT"), ("chep_runs", "leap_at", "TEXT"),
    ("invoices", "eway", "TEXT"), ("invoices", "unit_size", "REAL"),
]


NOT_SET_ON_VERCEL = ("This website has no database set: add TURSO_DATABASE_URL and TURSO_AUTH_TOKEN in "
                     "Vercel > Settings > Environment Variables and redeploy.")


def _connect():
    cloud = config.cloud_db()
    if config.ON_VERCEL and not cloud:
        # never fall back to an empty /tmp database on Vercel - it looks like all data is gone
        raise DatabaseUnavailable(NOT_SET_ON_VERCEL)
    if cloud:
        from .turso import Connection
        return Connection(*cloud)
    con = sqlite3.connect(config.DB_FILE, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


# ---------------------------------------------------------------- per-module databases (CHEP / DQMS)
# In cloud mode the CHEP and DQMS pages read their old websites' Turso databases directly (see
# config.module_cloud_db). Those databases have the old table names: runs (not chep_runs / dqms_runs).
MODULE_RENAMES = {"chep": {"chep_runs": "runs"}, "dqms": {"dqms_runs": "runs"}}
# columns the old apps added over time (same list as their own db.py)
MODULE_MIGRATIONS = {"chep": [("batches", "data", "BLOB"), ("runs", "leap_status", "TEXT"),
                              ("runs", "leap_result", "TEXT"), ("runs", "leap_at", "TEXT")],
                     "dqms": [("invoices", "eway", "TEXT"), ("invoices", "unit_size", "REAL")]}
_mod_ready = set()


class ModuleConnection:
    """A module's own database, with the hub's table names turned back into the old app's names."""

    def __init__(self, con, renames):
        import re
        self.con = con
        self._subs = [(re.compile(rf"\b{a}\b"), b) for a, b in renames.items()]

    def _sql(self, sql):
        for rx, b in self._subs:
            sql = rx.sub(b, sql)
        return sql

    def execute(self, sql, args=()):
        return self.con.execute(self._sql(sql), args)

    def executemany(self, sql, seq):
        return self.con.executemany(self._sql(sql), seq)

    def executescript(self, script):
        return self.con.executescript(self._sql(script))

    def commit(self):
        return self.con.commit()

    def close(self):
        return self.con.close()


def module_db(module):
    """The database a module's code works on: its own Turso database in cloud mode, else the hub's."""
    cloud = config.module_cloud_db(module)
    if not cloud:
        return get_db()
    key = f"mod_{module}"
    con = getattr(_local, key, None)
    if con is None:
        try:
            from .turso import Connection
            con = ModuleConnection(Connection(*cloud), MODULE_RENAMES.get(module, {}))
        except Exception as e:  # noqa: BLE001
            raise DatabaseUnavailable(str(e))
        setattr(_local, key, con)
    if module not in _mod_ready:
        with _init_lock:
            if module not in _mod_ready:
                try:
                    for table, col, typ in MODULE_MIGRATIONS.get(module, []):
                        cols = [r[1] for r in con.con.execute(f"PRAGMA table_info({table})").fetchall()]
                        if cols and col not in cols:
                            try:
                                con.con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
                                con.commit()
                            except Exception as e:  # noqa: BLE001
                                if "duplicate column" not in str(e).lower():
                                    raise
                except Exception as e:  # noqa: BLE001
                    raise DatabaseUnavailable(str(e))
                _mod_ready.add(module)
    return con


def commit_all():
    """Send queued Turso writes of the hub and module databases (called after every request)."""
    for key in ("con", "mod_chep", "mod_dqms"):
        con = getattr(_local, key, None)
        if con is not None:
            try:
                con.commit()
            except Exception:  # noqa: BLE001
                pass


def migrate(con):
    con.executescript(SCHEMA)
    for table, col, typ in MIGRATIONS:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
        if col not in cols:
            try:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
                con.commit()
            except Exception as e:  # noqa: BLE001 - the website and the PC may add it at the same moment
                if "duplicate column" not in str(e).lower():
                    raise
    con.commit()
    from .seed import seed_open_items
    seed_open_items(con)


def get_db():
    global _ready
    con = getattr(_local, "con", None)
    if con is None:
        try:
            con = _connect()
        except Exception as e:  # noqa: BLE001
            raise DatabaseUnavailable(str(e))
        _local.con = con
    if not _ready:
        with _init_lock:
            if not _ready:
                try:
                    migrate(con)
                except Exception as e:  # noqa: BLE001
                    raise DatabaseUnavailable(str(e))
                _ready = True
    return con


def rows(sql, args=()):
    return [dict(r) for r in get_db().execute(sql, args).fetchall()]


def one(sql, args=()):
    r = get_db().execute(sql, args).fetchone()
    return dict(r) if r else None


def get_setting(key, default=None):
    r = one("SELECT value FROM settings WHERE key=?", (key,))
    return json.loads(r["value"]) if r else default


def set_setting(key, value):
    con = get_db()
    con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)))
    con.commit()


def log(module, action, detail=""):
    """One line in the hub's activity list (Today page)."""
    from datetime import datetime
    try:
        con = get_db()
        con.execute("INSERT INTO activity(at, module, action, detail) VALUES(?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"), module, action, str(detail)[:500]))
        con.commit()
    except Exception:  # noqa: BLE001 - never let the log break real work
        pass
