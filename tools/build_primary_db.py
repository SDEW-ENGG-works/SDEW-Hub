"""ONE database for everything: fill the hub's primary Turso database (TURSO_DATABASE_URL / TURSO_AUTH_TOKEN,
e.g. a new Mumbai database) from

    this PC's hub database (data\\sdew_hub.db)   Supplementary Bill, GRIN & Payments, POs, follow-ups, ... (all tables)
    the CHEP website's Turso database          CHEP_TURSO_DATABASE_URL / CHEP_TURSO_AUTH_TOKEN  (live CHEP data)
    the DQMS website's Turso database          DQMS_TURSO_DATABASE_URL / DQMS_TURSO_AUTH_TOKEN  (live DQMS data)

CHEP / DQMS: the website's rows win; rows only this PC has are added too (new ids where an id is taken).
The old CHEP / DQMS databases are only READ - never changed.

    python tools\\build_primary_db.py --check     counts per table, changes nothing
    python tools\\build_primary_db.py             builds data\\sdew_hub_unified.db and copies it to the primary database
    python tools\\build_primary_db.py --local     only builds data\\sdew_hub_unified.db (to look at first)

Afterwards: USE_CLOUD_DB=1 in this PC's .env, and the same TURSO_* in Vercel - PC and website share one database.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hub import config  # noqa: E402
from hub.db import migrate  # noqa: E402
from hub.turso import Connection  # noqa: E402

OUT = os.path.join(config.DATA_DIR, "sdew_hub_unified.db")
BATCH = 300

# (module, table in the old website DB, table in the hub, natural key to recognise the same row, newer-stamp)
CHEP = [("batches", "batches", ("name", "uploaded_at"), None),
        ("runs", "chep_runs", ("created_at", "file_name"), None),
        ("part_types", "part_types", ("part",), "updated_at"),
        ("templates", "templates", ("name", "uploaded_at"), None),
        ("leap_jobs", "leap_jobs", ("created_at", "run_id"), None)]
DQMS = [("invoices", "invoices", ("inv_no",), "uploaded_at"),
        ("delivery_requests", "delivery_requests", ("dr_no", "part"), "uploaded_at"),
        ("portal_status", "portal_status", ("inv_no", "seq"), "uploaded_at"),
        ("line_overrides", "line_overrides", ("po_no", "part"), "updated_at"),
        ("runs", "dqms_runs", ("created_at", "file_name"), None)]
AUTO_ID = {"batches", "chep_runs", "templates", "leap_jobs", "dqms_runs"}


def env():
    return config.read_env()


def snapshot_local():
    """Consistent copy of the PC's hub database (includes what is still in the -wal file)."""
    src = sqlite3.connect(config.DB_FILE)
    tmp = os.path.join(tempfile.mkdtemp(prefix="hubunify_"), "work.db")
    dst = sqlite3.connect(tmp)
    src.backup(dst)
    src.close()
    dst.row_factory = sqlite3.Row
    migrate(dst)
    return dst, tmp


def cloud_rows(con, table):
    names = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    return [dict(r) for r in con.execute(f"SELECT * FROM {table}").fetchall()] if table in names else []


def merge_module(work, cloud, spec, prefix, log):
    """Website rows first, then the PC's extra rows. Returns {(hub table): (website, pc only added)}."""
    remap = {}           # (hub table, old pc id) -> new id
    out = {}
    for old, new, key, stamp in spec:
        cols = [r[1] for r in work.execute(f"PRAGMA table_info({new})").fetchall()]
        pc = [dict(r) for r in work.execute(f"SELECT * FROM {new}").fetchall()]
        web = cloud_rows(cloud, old)
        seen, ids, rows_out = {}, set(), []
        for r in web:
            k = tuple(r.get(x) for x in key)
            seen[k] = len(rows_out)
            rows_out.append(r)
            if "id" in r:
                ids.add(r["id"])
        added = 0
        nxt = max(ids or {0}) + 1
        for r in pc:
            k = tuple(r.get(x) for x in key)
            if k in seen:
                if stamp and str(r.get(stamp) or "") > str(rows_out[seen[k]].get(stamp) or ""):
                    rows_out[seen[k]] = r          # the PC changed it later
                continue
            r = dict(r)
            if new in AUTO_ID and r.get("id") in ids:
                remap[(new, r["id"])] = nxt
                r["id"] = nxt
                nxt += 1
            if "id" in r:
                ids.add(r["id"])
            rows_out.append(r)
            added += 1
        for r in rows_out:      # references of rows that got a new id
            if new == "chep_runs" and (("batches", r.get("batch_id")) in remap):
                r["batch_id"] = remap[("batches", r["batch_id"])]
            if new == "leap_jobs" and (("chep_runs", r.get("run_id")) in remap):
                r["run_id"] = remap[("chep_runs", r["run_id"])]
            if new == "invoices" and (("dqms_runs", r.get("run_id")) in remap):
                r["run_id"] = remap[("dqms_runs", r["run_id"])]
        work.execute(f"DELETE FROM {new}")
        if rows_out:
            use = [c for c in cols if any(c in r for r in rows_out[:50])]
            work.executemany(f"INSERT OR REPLACE INTO {new}({', '.join(use)}) VALUES({', '.join('?' * len(use))})",
                             [tuple(r.get(c) for c in use) for r in rows_out])
        out[new] = (len(web), added)
        log(f"  {prefix}.{old:<18} -> {new:<18} website {len(web):>6}  + PC only {added:>5}  = {len(rows_out):>6}")
    # settings: website keys win, PC-only keys stay
    for r in cloud_rows(cloud, "settings"):
        work.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (f"{prefix}.{r['key']}", r["value"]))
    return out


def merge_dqms_extra(work, cloud, log):
    """DQMS batches: the newer DQMS report wins. POs only the DQMS website has: added to the shared PO tables."""
    web_rep = next((json.loads(r["value"] or "{}") for r in cloud_rows(cloud, "settings") if r["key"] == "dqms_report"), {})
    pc = work.execute("SELECT value FROM settings WHERE key='dqms.dqms_report'").fetchone()
    t = lambda d: str(d.get("report_time") or d.get("uploaded_at") or "")  # noqa: E731
    web_b = cloud_rows(cloud, "dqms_batches")
    if web_b and (not pc or t(web_rep) >= t(json.loads(pc[0] or "{}"))):
        work.execute("DELETE FROM dqms_batches")
        work.executemany("INSERT OR REPLACE INTO dqms_batches(batch_no, part, descr, total, consumed, balance, created) "
                         "VALUES(?,?,?,?,?,?,?)", [(r["batch_no"], r["part"], r["descr"], r["total"], r["consumed"],
                                                    r["balance"], r["created"]) for r in web_b])
        log(f"  dqms.dqms_batches -> website's report ({t(web_rep)}), {len(web_b)} batches")
    else:
        log("  dqms.dqms_batches -> this PC's report (newer)")
        if pc:
            work.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('dqms.dqms_report', ?)", (pc[0],))
    have = {(r[0], r[1]) for r in work.execute("SELECT po_no, part FROM po_items")}
    extra = [r for r in cloud_rows(cloud, "po_items") if (r["po_no"], r["part"]) not in have]
    for r in extra:
        work.execute("INSERT OR IGNORE INTO po_items(po_no, part, item, descr, rate, blocks) VALUES(?,?,?,?,?,?)",
                     (r["po_no"], r["part"], r["item"], r["descr"], r["rate"], "[]"))
    heads = {r[0] for r in work.execute("SELECT po_no FROM po_headers")}
    for r in cloud_rows(cloud, "po_headers"):
        if r["po_no"] not in heads:
            work.execute("INSERT INTO po_headers(po_no, plant, items, source, uploaded_at) VALUES(?,?,?,?,?)",
                         (r["po_no"], r.get("plant"), r.get("items"), r.get("source") or "DQMS website", r.get("uploaded_at")))
    log(f"  dqms PO lines only the website had: {len(extra)}")


def upload(work, url, token, log):
    cloud = Connection(url, token, timeout=300)
    migrate(cloud)
    tables = [r[0] for r in work.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for t in tables:
        cols = [r[1] for r in work.execute(f"PRAGMA table_info({t})")]
        cloud.execute(f"DELETE FROM {t}")
        cloud.commit()
        rows = work.execute(f"SELECT {', '.join(cols)} FROM {t}").fetchall()
        sql = f"INSERT INTO {t}({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})"
        for i in range(0, len(rows), BATCH):
            for r in rows[i:i + BATCH]:
                cloud.execute(sql, tuple(r))
            cloud.commit()
        n = cloud.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
        flag = "" if n == len(rows) else "   <- MISMATCH"
        log(f"  {t:<20} {len(rows):>7} rows  (cloud now {n}){flag}")


def main(argv):
    e = env()
    lines = []

    def log(s):
        print(s)
        lines.append(s)

    url, token = e.get("TURSO_DATABASE_URL"), e.get("TURSO_AUTH_TOKEN")
    if not (url and token) and "--local" not in argv:
        sys.exit("Put the NEW primary database in .env first:  TURSO_DATABASE_URL=...  TURSO_AUTH_TOKEN=...")
    for k in ("CHEP", "DQMS"):
        if not (e.get(f"{k}_TURSO_DATABASE_URL") and e.get(f"{k}_TURSO_AUTH_TOKEN")):
            sys.exit(f"{k}_TURSO_DATABASE_URL / {k}_TURSO_AUTH_TOKEN missing in .env")
        if url and e.get(f"{k}_TURSO_DATABASE_URL") == url:
            sys.exit(f"TURSO_DATABASE_URL is the old {k} database - create a NEW database for the hub.")
    chep = Connection(e["CHEP_TURSO_DATABASE_URL"], e["CHEP_TURSO_AUTH_TOKEN"])
    dqms = Connection(e["DQMS_TURSO_DATABASE_URL"], e["DQMS_TURSO_AUTH_TOKEN"])
    work, tmp = snapshot_local()
    log(f"Building one database from: this PC ({config.DB_FILE}) + CHEP website + DQMS website")
    if "--check" in argv:
        for spec, con, p in ((CHEP, chep, "chep"), (DQMS, dqms, "dqms")):
            for old, new, *_ in spec:
                n_pc = work.execute(f"SELECT COUNT(*) FROM {new}").fetchone()[0]
                log(f"  {p}.{old:<18} website {len(cloud_rows(con, old)):>6}   this PC ({new}) {n_pc:>6}")
        if url:
            cl = Connection(url, token)
            names = {r["name"] for r in cl.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            log(f"Primary database now has {len(names)} tables" + (" (empty)" if not names else ""))
        return
    merge_module(work, chep, CHEP, "chep", log)
    merge_module(work, dqms, DQMS, "dqms", log)
    merge_dqms_extra(work, dqms, log)
    rep = dict(at=datetime.now().isoformat(timespec="seconds"), log=lines[-40:])
    work.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('hub.unified', ?)", (json.dumps(rep),))
    work.execute("INSERT INTO activity(at, module, action, detail) VALUES(?,?,?,?)",
                 (rep["at"], "hub", "one database", "PC + CHEP website + DQMS website merged"))
    work.commit()
    work.close()
    shutil.copy2(tmp, OUT)
    log(f"Built {OUT}")
    if "--local" in argv:
        return
    if "--yes" not in argv and input("\nReplace EVERYTHING in the primary database with this? (yes/no): ").strip().lower() not in ("y", "yes"):
        print("Primary database not changed.")
        return
    work = sqlite3.connect(OUT)
    upload(work, url, token, log)
    print("\nDone. Next: USE_CLOUD_DB=1 in this .env (restart start.bat) and the same TURSO_* in Vercel.")


if __name__ == "__main__":
    main(sys.argv[1:])
