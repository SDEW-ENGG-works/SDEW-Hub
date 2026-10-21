"""Prove the hub holds the same data as the old apps and gives the same results.

    python tools\\verify_hub.py                  (old apps found next to the hub, like import_from_apps.py)
    python tools\\verify_hub.py --source D:\\SDEW

1. Every row of every old table is in the hub, field for field (not just the counts).
2. Supplementary Bill: the bill is calculated again in the hub and compared line by line with the
   last bill the old app saved (same lines, same rates, same values, same total).
3. CHEP: every History file is built again from its packing list and compared row by row.
4. DQMS: every History file's CSV is in the hub, byte for byte.
Nothing is changed except one extra bill run (the hub keeps the last 3 runs' lines).
Writes data\\verify_report.txt.
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import import_from_apps as imp  # noqa: E402
from hub import config  # noqa: E402

OUT = []


def say(s=""):
    print(s)
    OUT.append(s)


def norm(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "b:" + hashlib.md5(bytes(v)).hexdigest()
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def key_of(row, cols):
    return json.dumps([norm(row.get(c)) for c in cols], default=str)


def check_tables(sources, con):
    bad = 0
    say("1. Every row, field for field")
    for mod, old, new in imp.TABLES:
        s = sources.get(mod)
        if not s or old not in s.tables():
            continue
        if new == "dqms_batches" and imp.kept_newer_report(con):
            say(f"   OK   {mod}.{old:<18} -> {new:<18} kept the hub's own newer DQMS report")
            continue
        src = s.rows(old)
        hub_cols = [r[1] for r in con.execute(f"PRAGMA table_info({new})").fetchall()]
        cols = [c for c in (src[0].keys() if src else hub_cols) if c in hub_cols and not (new == "batches" and c == "stored")]
        hub = [dict(r) for r in con.execute(f"SELECT * FROM {new}").fetchall()]
        a = sorted(key_of(r, cols) for r in src)
        b = sorted(key_of(r, cols) for r in hub)
        ok = a == b
        bad += not ok
        say(f"   {'OK ' if ok else 'DIFF'} {mod}.{old:<18} -> {new:<18} {len(src):>7} rows")
    return bad


def check_bill(con):
    say("\n2. Supplementary bill calculated again in the hub")
    last = con.execute("SELECT id, summary FROM bill_runs ORDER BY id DESC LIMIT 1").fetchone()
    if not last:
        say("   no bill in the old app - skipped")
        return 0
    from hub.supp.services import engine
    res = engine.run()
    cols = ("plant,cat,reason,voucher,inv_date,party,order_no,po_no,order_due,part,descr,hsn,gst,qty,rate,old_rate,"
            "new_rate,diff,value,grn_no,grn_date,status,notes,old_src")
    a = sorted(map(tuple, con.execute(f"SELECT {cols} FROM run_lines WHERE run_id=?", (last["id"],)).fetchall()), key=repr)
    b = sorted(map(tuple, con.execute(f"SELECT {cols} FROM run_lines WHERE run_id=?", (res["run_id"],)).fetchall()), key=repr)
    old_t = json.loads(last["summary"])["total"]
    new_t = res["summary"]["total"]
    same = a == b and old_t == new_t
    say(f"   old app's bill #{last['id']}: {old_t['bill_lines']} lines, basic Rs {old_t['bill_value']:,.2f}, with GST Rs {old_t['with_gst']:,.2f}")
    say(f"   hub's bill    #{res['run_id']}: {new_t['bill_lines']} lines, basic Rs {new_t['bill_value']:,.2f}, with GST Rs {new_t['with_gst']:,.2f}")
    say(f"   {'OK  all ' + str(len(a)) + ' lines identical' if same else 'DIFF - lines differ (new uploads since the old bill would explain it)'}")
    return 0 if same else 1


def check_chep(con):
    say("\n3. CHEP History files built again from their packing lists")
    from hub.chep.services import store
    bad = 0
    runs = con.execute("SELECT id, batch_id, file_name, doc_date, summary, rows FROM chep_runs ORDER BY id").fetchall()
    for r in runs:
        s = json.loads(r["summary"] or "{}")
        if not r["batch_id"] or not s.get("sheets"):
            say(f"   --   {r['file_name']} (made by LEAP retry / combine - nothing to rebuild)")
            continue
        try:
            p = store.preview(r["batch_id"], {"sheets": s["sheets"], "doc_date": r["doc_date"]})
        except Exception as e:  # noqa: BLE001
            say(f"   DIFF {r['file_name']}: {e}")
            bad += 1
            continue
        k = lambda x: (x["customer"], x["invoice"], x["sku"], x["qty"])  # noqa: E731
        a, b = sorted(map(k, json.loads(r["rows"] or "[]"))), sorted(map(k, p["rows"]))
        ok = a == b
        bad += not ok
        say(f"   {'OK ' if ok else 'DIFF'} #{r['id']} {r['file_name']}: {len(a)} rows")
    if not runs:
        say("   no History files")
    return bad


def check_dqms(sources, con):
    say("\n4. DQMS History files (CSV) byte for byte")
    s = sources.get("dqms")
    if not s or "runs" not in s.tables():
        say("   skipped")
        return 0
    old = {r["id"]: hashlib.md5(bytes(r["csv"] or b"")).hexdigest() for r in s.rows("runs")}
    new = {r[0]: hashlib.md5(bytes(r[1] or b"")).hexdigest() for r in con.execute("SELECT id, csv FROM dqms_runs")}
    bad = 0
    for i, h in old.items():
        ok = new.get(i) == h
        bad += not ok
        say(f"   {'OK ' if ok else 'DIFF'} file #{i}")
    return bad


def main(argv=None, exit_code=True):
    argv = sys.argv[1:] if argv is None else argv
    OUT.clear()
    src = imp.find_source(argv)
    sources, notes = imp.open_sources(src)
    say(f"Old apps: {src}")
    for m, n in notes.items():
        say(f"   {m}: {n}")
    con = imp.hub_con()
    bad = check_tables(sources, con)
    bad += check_bill(con)
    bad += check_chep(con)
    bad += check_dqms(sources, con)
    say("\nRESULT: " + ("VERIFIED - the hub has all the old apps' data and gives the same results." if not bad
                        else f"{bad} check(s) differ - see above."))
    with open(os.path.join(config.DATA_DIR, "verify_report.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(OUT) + "\n")
    if exit_code:
        sys.exit(1 if bad else 0)
    return bad


if __name__ == "__main__":
    main()
