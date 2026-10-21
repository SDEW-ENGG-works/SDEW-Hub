"""Copy ALL the data of the three old apps into the hub's database (data\\sdew_hub.db).

    python tools\\import_from_apps.py                 import (asks first when the hub already has data)
    python tools\\import_from_apps.py --yes           import without asking
    python tools\\import_from_apps.py --check         only compare old apps vs hub, change nothing
    python tools\\import_from_apps.py --source D:\\SDEW  folder holding SupplementaryBill, CHEPTransfer, DQMSUpload

The old apps are only READ - their folders and databases are never changed.
  SupplementaryBill\\data\\supp_bill.db  -> POs, GRIN, Sales Register, GRN sheet, bills, uploaded-file list, settings
  CHEPTransfer                          -> the CHEP website's Turso database (the live CHEP data)
  DQMSUpload                            -> the DQMS website's Turso database merged with data\\dqms.db on the PC
                                           (invoices, DQMS batches, DRs, typed line items, portal status, History)
  (Turso keys come from the old apps' .env files and are copied into the hub's .env as
   CHEP_TURSO_DATABASE_URL / CHEP_TURSO_AUTH_TOKEN and DQMS_TURSO_DATABASE_URL / DQMS_TURSO_AUTH_TOKEN.
   When Turso cannot be reached, the PC copy is used and the import says so - run it again when online.)
Uploaded files, GRIN / DQMS downloads and LEAP files are copied into the hub's data folder too.
Logins in the old .env files (TAFE, LEAP, APP_PASSWORD) are added to the hub's .env when it does not have them.
The hub database is backed up first to data\\backups\\.
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

from hub import config  # noqa: E402

APPS = {"supp": ("SupplementaryBill", "supp_bill.db"), "chep": ("CHEPTransfer", "chep.db"),
        "dqms": ("DQMSUpload", "dqms.db")}

# (module, old table, hub table)
TABLES = [
    ("supp", "files", "files"), ("supp", "po_headers", "po_headers"), ("supp", "po_items", "po_items"),
    ("supp", "grin_lines", "grin_lines"), ("supp", "sales_lines", "sales_lines"), ("supp", "grn_sheet", "grn_sheet"),
    ("supp", "runs", "bill_runs"), ("supp", "run_lines", "run_lines"),
    ("chep", "batches", "batches"), ("chep", "runs", "chep_runs"), ("chep", "part_types", "part_types"),
    ("chep", "templates", "templates"), ("chep", "leap_jobs", "leap_jobs"),
    ("dqms", "invoices", "invoices"), ("dqms", "dqms_batches", "dqms_batches"), ("dqms", "line_overrides", "line_overrides"),
    ("dqms", "portal_status", "portal_status"), ("dqms", "runs", "dqms_runs"), ("dqms", "delivery_requests", "delivery_requests"),
]
FOLDERS = [("supp", "uploads", os.path.join("uploads", "supp")), ("supp", "grin_downloads", "grin_downloads"),
           ("chep", "uploads", os.path.join("uploads", "chep")), ("chep", "leap", "leap"),
           ("dqms", "uploads", os.path.join("uploads", "dqms")), ("dqms", "dqms_downloads", "dqms_downloads")]
ENV_CARRY = ["TAFE_USER", "TAFE_PASS", "LEAP_USER", "LEAP_PASS", "APP_PASSWORD"]


def find_source(argv):
    if "--source" in argv:
        return argv[argv.index("--source") + 1]
    cands = [os.environ.get("SDEW_SOURCE") or config.read_env().get("SDEW_SOURCE") or ""]
    up1, up2 = os.path.dirname(ROOT), os.path.dirname(os.path.dirname(ROOT))
    cands += [os.path.join(up1, "SDEW"), os.path.join(up2, "SDEW"), up1, up2]
    for c in cands:
        if c and any(os.path.isdir(os.path.join(c, a)) for a, _ in APPS.values()):
            return c
    sys.exit("Could not find the old apps. Run with --source <folder holding SupplementaryBill, CHEPTransfer, DQMSUpload>.")


def read_env(path):
    vals = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    vals[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return vals


def snapshot_sqlite(path):
    """Read-only copy of an SQLite file (includes what is still in its -wal file)."""
    if not os.path.exists(path):
        return None
    tmp = tempfile.mkdtemp(prefix="hubimport_")
    for ext in ("", "-wal", "-shm"):
        if os.path.exists(path + ext) and os.path.getsize(path + ext) > 0:
            shutil.copy2(path + ext, os.path.join(tmp, "src.db" + ext))
    src = sqlite3.connect(os.path.join(tmp, "src.db"))
    out = sqlite3.connect(os.path.join(tmp, "snap.db"))
    src.backup(out)
    src.close()
    out.row_factory = sqlite3.Row
    return out


class CloudSource:
    """The CHEP website's Turso database, read with the hub's Turso client."""

    def __init__(self, url, token):
        from hub.turso import Connection
        self.con = Connection(url, token)

    def tables(self):
        return {r["name"] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    def rows(self, table):
        return [dict(r) for r in self.con.execute(f"SELECT * FROM {table}").fetchall()]


class LocalSource:
    def __init__(self, con):
        self.con = con

    def tables(self):
        return {r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    def rows(self, table):
        return [dict(r) for r in self.con.execute(f"SELECT * FROM {table}").fetchall()]


class MemSource:
    """Rows held in memory (DQMS: the website's cloud data merged with the PC's own copy)."""

    def __init__(self, tables):
        self.data = tables

    def tables(self):
        return set(self.data)

    def rows(self, table):
        return [dict(r) for r in self.data.get(table, [])]


# Turso keys of each old app, as copied into the hub's .env (the old app's own .env is read first)
CLOUD_KEYS = {"chep": ("CHEP_TURSO_DATABASE_URL", "CHEP_TURSO_AUTH_TOKEN"),
              "dqms": ("DQMS_TURSO_DATABASE_URL", "DQMS_TURSO_AUTH_TOKEN")}


def cloud_creds(mod, app_dir):
    env = read_env(os.path.join(app_dir, ".env"))
    url, token = env.get("TURSO_DATABASE_URL"), env.get("TURSO_AUTH_TOKEN")
    if url and token and "xxxx" not in url:
        return url, token
    hub = read_env(config.ENV_FILE)
    k_url, k_tok = CLOUD_KEYS[mod]
    if hub.get(k_url) and hub.get(k_tok):
        return hub[k_url], hub[k_tok]
    return None


def _newer(a, b, field):
    return a if str(a.get(field) or "") >= str(b.get(field) or "") else b


def merge_dqms(cloud, local):
    """Website (Turso) + PC (dqms.db) -> one set of DQMS tables. Nothing from either side is lost:
    the same invoice / DR line / typed line item / portal row -> the one saved last;
    History files from both (same file made twice -> once); DQMS batches from the newer report."""
    def rows(src, t):
        return src.rows(t) if src and t in src.tables() else []

    out = {}
    for t, key, stamp in (("invoices", ("inv_no",), "uploaded_at"),
                          ("delivery_requests", ("dr_no", "part"), "uploaded_at"),
                          ("portal_status", ("inv_no", "seq"), "uploaded_at"),
                          ("line_overrides", ("po_no", "part"), "updated_at"),
                          ("po_headers", ("po_no",), "uploaded_at"),
                          ("po_items", ("po_no", "part"), None)):
        m = {}
        for r in rows(cloud, t) + rows(local, t):
            k = tuple(r.get(x) for x in key)
            m[k] = _newer(m[k], r, stamp) if (k in m and stamp) else r
        out[t] = list(m.values())

    # History: keep the PC's ids; a website-only file gets a new id if its id is taken
    runs, seen, ids, remap = [], set(), set(), {}
    for r in rows(local, "runs"):
        runs.append(r)
        seen.add((r.get("created_at"), r.get("file_name")))
        ids.add(r["id"])
    nxt = max(ids or {0}) + 1
    for r in rows(cloud, "runs"):
        k = (r.get("created_at"), r.get("file_name"))
        if k in seen:
            continue
        r = dict(r)
        if r["id"] in ids:
            remap[r["id"]] = nxt
            r["id"] = nxt
            nxt += 1
        ids.add(r["id"])
        seen.add(k)
        runs.append(r)
    out["runs"] = runs
    cloud_inv = {r["inv_no"] for r in rows(cloud, "invoices")}
    for r in out["invoices"]:
        if r.get("run_id") in remap and r["inv_no"] in cloud_inv:
            r["run_id"] = remap[r["run_id"]]

    # settings: union; the DQMS report info goes with the batch table of the newer report
    st = {}
    for r in rows(cloud, "settings") + rows(local, "settings"):
        st.setdefault(r["key"], r)
    rep = {}
    for name, src in (("cloud", cloud), ("local", local)):
        for r in rows(src, "settings"):
            if r["key"] == "dqms_report":
                try:
                    rep[name] = json.loads(r["value"] or "{}")
                except ValueError:
                    rep[name] = {}
    t = {n: (v.get("report_time") or v.get("uploaded_at") or "") for n, v in rep.items()}
    pick = "local" if t.get("local", "") >= t.get("cloud", "") else "cloud"
    if not rows(local if pick == "local" else cloud, "dqms_batches"):
        pick = "cloud" if pick == "local" else "local"
    out["dqms_batches"] = rows(local if pick == "local" else cloud, "dqms_batches")
    for r in rows(local if pick == "local" else cloud, "settings"):
        if r["key"] == "dqms_report":
            st["dqms_report"] = r
    out["settings"] = list(st.values())
    return MemSource(out), pick


def open_sources(src_dir):
    """Supplementary Bill: the PC's database (never hosted).
    CHEP: the website's Turso database (where the live data is).
    DQMS: the website's Turso database merged with the PC's database."""
    out, notes = {}, {}
    for mod, (folder, dbname) in APPS.items():
        app = os.path.join(src_dir, folder)
        if not os.path.isdir(app):
            notes[mod] = "folder not found - skipped"
            continue
        local_con = snapshot_sqlite(os.path.join(app, "data", dbname))
        local = LocalSource(local_con) if local_con else None
        cloud, why = None, ""
        if mod in CLOUD_KEYS:
            cred = cloud_creds(mod, app)
            if cred:
                try:
                    cloud = CloudSource(*cred)
                    cloud.tables()
                except Exception as e:  # noqa: BLE001
                    cloud, why = None, f"Turso not reachable ({e})"
            else:
                why = "no Turso keys in .env"
        if mod == "chep" and cloud:
            out[mod], notes[mod] = cloud, "website's Turso database (the live CHEP data)"
        elif mod == "dqms" and cloud:
            out[mod], pick = merge_dqms(cloud, local)
            notes[mod] = (f"website's Turso database + data\\{dbname} on this PC, merged "
                          f"(DQMS batches from the {'PC' if pick == 'local' else 'website'}'s newer report)")
        elif local:
            out[mod] = local
            notes[mod] = f"data\\{dbname}" + (f" - {why}, run again when online!" if why and mod != "supp" else "")
        else:
            notes[mod] = f"data\\{dbname} not found - skipped"
    return out, notes


def hub_con():
    con = sqlite3.connect(config.DB_FILE, timeout=60)
    con.row_factory = sqlite3.Row
    from hub.db import migrate
    migrate(con)
    return con


def kept_newer_report(con):
    r = con.execute("SELECT value FROM settings WHERE key='hub.import'").fetchone()
    return bool(r and json.loads(r[0]).get("kept_hub_dqms_report"))


def compare(sources, con):
    print(f"\n{'table':<34} {'old app':>9} {'hub':>9}")
    diff = 0
    for mod, old, new in TABLES:
        s = sources.get(mod)
        if not s:
            continue
        n_old = len(s.rows(old)) if old in s.tables() else 0
        n_new = con.execute(f"SELECT COUNT(*) FROM {new}").fetchone()[0]
        if new == "dqms_batches" and kept_newer_report(con):
            print(f"{mod + '.' + old + ' -> ' + new:<34} {n_old:>9} {n_new:>9}   (the hub's own newer DQMS report)")
            continue
        flag = "" if n_old == n_new else "   <- differs"
        diff += bool(flag)
        print(f"{mod + '.' + old + ' -> ' + new:<34} {n_old:>9} {n_new:>9}{flag}")
    return diff


def copy_table(con, src_rows, table, extra=None):
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    con.execute(f"DELETE FROM {table}")
    if not src_rows:
        return 0
    use = [c for c in cols if c in src_rows[0] or (extra and c in extra)]
    sql = f"INSERT OR REPLACE INTO {table}({', '.join(use)}) VALUES({', '.join('?' * len(use))})"
    con.executemany(sql, [tuple(r.get(c, (extra or {}).get(c)) for c in use) for r in src_rows])
    return len(src_rows)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    src_dir = find_source(argv)
    print(f"Old apps folder: {src_dir}")
    sources, notes = open_sources(src_dir)
    for m, n in notes.items():
        print(f"  {m:<5} {n}")
    con = hub_con()
    if "--check" in argv:
        d = compare(sources, con)
        print("\nAll tables match." if not d else f"\n{d} table(s) differ - run without --check to import.")
        return
    has_data = con.execute("SELECT COUNT(*) FROM sales_lines").fetchone()[0] or con.execute(
        "SELECT COUNT(*) FROM chep_runs").fetchone()[0] or con.execute("SELECT COUNT(*) FROM dqms_runs").fetchone()[0]
    if has_data and "--yes" not in argv:
        ans = input("\nThe hub already has data. Replace it with the old apps' data? (yes/no): ").strip().lower()
        if ans not in ("y", "yes"):
            print("Nothing changed.")
            return
    con.close()
    if os.path.exists(config.DB_FILE):
        bdir = os.path.join(config.DATA_DIR, "backups")
        os.makedirs(bdir, exist_ok=True)
        b = os.path.join(bdir, f"sdew_hub_before_import_{datetime.now():%Y%m%d_%H%M%S}.db")
        s, d = sqlite3.connect(config.DB_FILE), sqlite3.connect(b)
        s.backup(d)
        d.close()
        s.close()
        print(f"Hub data saved first as {b}")
    con = hub_con()
    kept = con.execute("SELECT value FROM settings WHERE key='dqms.dqms_report'").fetchone()
    kept_rep = json.loads(kept[0]) if kept else None
    kept_batches = [dict(r) for r in con.execute("SELECT * FROM dqms_batches")] if kept else []

    report = dict(at=datetime.now().isoformat(timespec="seconds"), source=src_dir, sources=notes, tables={})
    dq_src = {}
    if "dqms" in sources and "po_headers" in sources["dqms"].tables():
        dq_src = {r["po_no"]: r.get("source") for r in sources["dqms"].rows("po_headers")}
    for mod, old, new in TABLES:
        s = sources.get(mod)
        if not s or old not in s.tables():
            continue
        data = s.rows(old)
        if new == "po_headers":
            for r in data:
                r["source"] = r.get("source") or dq_src.get(r["po_no"]) or "Supplementary Bill app"
        if new == "batches":   # file path of the old app -> the copy in the hub's data folder
            for r in data:
                if r.get("stored"):
                    r["stored"] = os.path.join(config.DATA_DIR, "uploads", "chep", os.path.basename(str(r["stored"]).replace("\\", "/")))
        n = copy_table(con, data, new)
        report["tables"][f"{mod}.{old} -> {new}"] = n
        print(f"  {mod}.{old:<18} -> {new:<18} {n:>7} rows")

    # POs that only the DQMS app had (typed in there from a PO .htm) - keep them too
    if "dqms" in sources and "po_items" in sources["dqms"].tables():
        have = {(r[0], r[1]) for r in con.execute("SELECT po_no, part FROM po_items")}
        extra = [r for r in sources["dqms"].rows("po_items") if (r["po_no"], r["part"]) not in have]
        for r in extra:
            con.execute("INSERT OR IGNORE INTO po_items(po_no,part,item,descr,rate,blocks) VALUES(?,?,?,?,?,?)",
                        (r["po_no"], r["part"], r["item"], r["descr"], r["rate"], "[]"))
        hh = {r[0] for r in con.execute("SELECT po_no FROM po_headers")}
        for r in sources["dqms"].rows("po_headers"):
            if r["po_no"] not in hh:
                con.execute("INSERT INTO po_headers(po_no,plant,items,source,uploaded_at) VALUES(?,?,?,?,?)",
                            (r["po_no"], r["plant"], r["items"], r.get("source") or "DQMS app", r.get("uploaded_at")))
        report["dqms_only_po_items"] = len(extra)
        if extra:
            print(f"  + {len(extra)} PO line(s) only the DQMS app had")

    # settings: each module's keys get its prefix ("app" -> "supp.app")
    con.execute("DELETE FROM settings WHERE key LIKE 'supp.%' OR key LIKE 'chep.%' OR key LIKE 'dqms.%'")
    for mod, s in sources.items():
        if "settings" in s.tables():
            for r in s.rows("settings"):
                con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (f"{mod}.{r['key']}", r["value"]))
    if kept_rep and kept_batches:
        src_rep = con.execute("SELECT value FROM settings WHERE key='dqms.dqms_report'").fetchone()
        src_rep = json.loads(src_rep[0]) if src_rep else {}
        t = lambda r: str(r.get("report_time") or r.get("uploaded_at") or "")  # noqa: E731
        if t(kept_rep) > t(src_rep):
            copy_table(con, kept_batches, "dqms_batches")
            con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('dqms.dqms_report', ?)", (json.dumps(kept_rep),))
            print(f"  kept the hub's own DQMS report ({t(kept_rep)}) - newer than the old app's")
            report["kept_hub_dqms_report"] = t(kept_rep)
    con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('hub.import', ?)", (json.dumps(report),))
    con.execute("INSERT INTO activity(at, module, action, detail) VALUES(?,?,?,?)",
                (report["at"], "hub", "imported old apps", f"from {src_dir}: " + ", ".join(f"{m}: {n}" for m, n in notes.items())))
    con.commit()

    # files kept by the old apps
    for mod, sub, dest in FOLDERS:
        src = os.path.join(src_dir, APPS[mod][0], "data", sub)
        if os.path.isdir(src):
            dst = os.path.join(config.DATA_DIR, dest)
            os.makedirs(dst, exist_ok=True)
            n = 0
            for f in os.listdir(src):
                if os.path.isfile(os.path.join(src, f)) and not os.path.exists(os.path.join(dst, f)):
                    shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
                    n += 1
            if n:
                print(f"  copied {n} file(s) from {APPS[mod][0]}\\data\\{sub}")

    # logins from the old .env files
    hub_env = read_env(config.ENV_FILE)
    add = {}
    for mod, folder in (("chep", "CHEPTransfer"), ("dqms", "DQMSUpload")):
        e = read_env(os.path.join(src_dir, folder, ".env"))
        k_url, k_tok = CLOUD_KEYS[mod]
        if e.get("TURSO_DATABASE_URL") and e.get("TURSO_AUTH_TOKEN") and "xxxx" not in e["TURSO_DATABASE_URL"]:
            if not hub_env.get(k_url):
                add[k_url], add[k_tok] = e["TURSO_DATABASE_URL"], e["TURSO_AUTH_TOKEN"]
    for folder in ("SupplementaryBill", "DQMSUpload", "CHEPTransfer"):
        for k, v in read_env(os.path.join(src_dir, folder, ".env")).items():
            if k in ENV_CARRY and v and not hub_env.get(k) and k not in add:
                add[k] = v
    if add:
        with open(config.ENV_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"\n# copied from the old apps' .env files on {datetime.now():%d-%m-%Y}\n")
            for k, v in add.items():
                fh.write(f"{k}={v}\n")
        print(f"  .env: added {', '.join(add)}")

    d = compare(sources, con)
    print("\nDone - every table matches the old apps." if not d else f"\nDone, but {d} table(s) differ - see above.")
    with open(os.path.join(config.DATA_DIR, "import_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)


if __name__ == "__main__":
    main()
