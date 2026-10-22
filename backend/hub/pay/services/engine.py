"""Match TAFE payment lines with the invoice register and decide what to mark.

Rules (taken from how the register was marked by hand):
  * An invoice is received when the export has a CREDIT line for it (doc type RF/RG/RE/NM/NS).
    Mark = payment voucher number in 'payment details', voucher date (dd.mm.yyyy) in 'payment date',
    columns A-F filled green.
  * Credit + debit note (ZK) on the same invoice: marked like any received invoice (Settings can change it).
  * Debit note only (ZK, no credit): NOT a payment - not marked.
  * Cash discount (KG) lines: no invoice - ignored.
  * A row that is already marked is never overwritten. If it carries a different number it is shown
    as "Marked with another number" (e.g. 1383032039 typed for 138032039) - tick it to correct.
  * Invoice numbers are compared after clean-up, so '9552/26/27' in the export finds '9552/26-27'.
"""
import json
from collections import OrderedDict
from datetime import datetime

from ..db import get_db, get_setting, one, rows
from ...http import ApiError
from .defaults import load_settings
from .ingest import file_path
from ...grin.services.norm import edit_distance
from .register import read_register

CATS = ["To mark", "Credit + debit note", "Amount differs", "Already marked", "Marked with another number",
        "Debit note only", "Not in register", "Cancelled in register"]
MARK_CATS = {"To mark", "Credit + debit note", "Amount differs"}


def latest_run_id():
    r = one("SELECT MAX(id) id FROM pm_runs")
    return r["id"] if r else None


def _pick_reg(regs, pvs):
    for r in regs:
        if r["mark"] and r["mark"] in pvs:
            return r
    for r in regs:
        if not r["mark"] and not r["cancelled"]:
            return r
    return regs[0]


def run_check():
    s = load_settings()
    fid = get_setting("register_file")
    path = file_path(fid) if fid else None
    if not path:
        raise ApiError("Upload the invoice register first.")
    lines = rows("SELECT * FROM pm_pay_lines ORDER BY pv_date, pv, rowid")
    if not lines:
        raise ApiError("Upload a TAFE payment details export first.")
    reg = read_register(path)
    by_key = {}
    for r in reg["rows"]:
        by_key.setdefault(r["key"], []).append(r)

    ignore = {t.upper() for t in s["ignore_doc_types"]}
    groups = OrderedDict()
    for l in lines:
        if l["doc_type"] in ignore or not l["inv_key"]:
            continue
        groups.setdefault(l["inv_key"], []).append(l)

    years = [r["key"][-5:] for r in reg["rows"] if "/" in r["key"]]
    fy = max(set(years), key=years.count) if years else ""
    out = []
    for key, ls in groups.items():
        credits = [l for l in ls if l["credit"] > 0]
        debits = [l for l in ls if l["debit"] > 0]
        cr = round(sum(l["credit"] for l in credits), 2)
        dr = round(sum(l["debit"] for l in debits), 2)
        main = max(credits or debits or ls, key=lambda l: (l["pv_date"], l["pv"]))
        credit_pvs = sorted({l["pv"] for l in credits})
        rec = dict(inv=ls[0]["inv_raw"], inv_key=key, pv=main["pv"], pv_date=main["pv_date"], credit=cr, debit=dr,
                   doc_types=" ".join(sorted({l["doc_type"] for l in ls})), reg_row=None, reg_date="",
                   reg_amount=None, reg_party="", reg_mark="", reg_mark_date="")
        notes = []
        if len(credit_pvs) > 1:
            notes.append(f"Paid in {len(credit_pvs)} vouchers: {', '.join(credit_pvs)} — latest used")
        regs = by_key.get(key, [])
        if not regs:
            cat = "Not in register"
            if "/" not in key:
                notes.append("No year in the invoice no. — check by hand")
            elif fy and key[-5:] != fy:
                notes.append(f"Year {key[-5:]} — register is {fy}")
        else:
            r = _pick_reg(regs, set(credit_pvs))
            rec.update(reg_row=r["row"], reg_date=r["date"], reg_amount=r["amount"], reg_party=r["party"],
                       reg_mark=r["mark"], reg_mark_date=r["mark_date"])
            if len(regs) > 1:
                notes.append(f"Invoice is {len(regs)} times in the register (rows {', '.join(str(x['row']) for x in regs)})")
            if not credits:
                cat = "Debit note only"
                notes.insert(0, f"Debit note ₹{dr:,.2f} only — not a payment")
            elif r["cancelled"]:
                cat = "Cancelled in register"
            elif r["mark"]:
                if r["mark"] in credit_pvs:
                    cat = "Already marked"
                else:
                    cat = "Marked with another number"
                    if r["mark"].isdigit() and edit_distance(r["mark"], rec["pv"]) <= 2:
                        notes.insert(0, f"Register has {r['mark']} — looks like a typo of {rec['pv']}. Tick to correct it")
                    else:
                        notes.insert(0, f"Register has {r['mark']} {r['mark_date']}; this payment is {rec['pv']}. Tick to overwrite")
            else:
                ratio = cr / r["amount"] if r["amount"] else None
                off = ratio is not None and not (s["min_ratio"] <= ratio <= s["max_ratio"])
                if off:
                    notes.append(f"Credit ₹{cr:,.2f} vs invoice ₹{r['amount']:,.2f} ({(ratio - 1) * 100:+.2f}%)")
                if debits:
                    cat = "Credit + debit note"
                    notes.insert(0, f"Debit note ₹{dr:,.2f} also against this invoice")
                elif off:
                    cat = "Amount differs"
                else:
                    cat = "To mark"
        if cat == "To mark":
            action = "mark"
        elif cat == "Credit + debit note":
            action = "mark" if s["mark_credit_debit"] else "skip"
        elif cat == "Amount differs":
            action = "mark" if s["mark_amount_differs"] else "skip"
        else:
            action = "skip"
        rec.update(cat=cat, action=action, note="; ".join(notes))
        out.append(rec)

    out.sort(key=lambda x: (CATS.index(x["cat"]), x["reg_row"] or 10 ** 9))
    summary = _summary(out, lines, s)
    con = get_db()
    cur = con.execute("INSERT INTO pm_runs(created_at, register_file, summary) VALUES(?,?,?)",
                      (datetime.now().isoformat(timespec="seconds"), fid, json.dumps(summary)))
    rid = cur.lastrowid
    con.executemany(
        "INSERT INTO pm_run_lines(run_id,seq,cat,action,inv,inv_key,reg_row,reg_date,reg_amount,reg_party,reg_mark,"
        "reg_mark_date,pv,pv_date,credit,debit,doc_types,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(rid, i, o["cat"], o["action"], o["inv"], o["inv_key"], o["reg_row"], o["reg_date"], o["reg_amount"],
          o["reg_party"], o["reg_mark"], o["reg_mark_date"], o["pv"], o["pv_date"], o["credit"], o["debit"],
          o["doc_types"], o["note"]) for i, o in enumerate(out)])
    # keep only the last 20 checks
    con.execute("DELETE FROM pm_run_lines WHERE run_id <= ?", (rid - 20,))
    con.execute("DELETE FROM pm_runs WHERE id <= ?", (rid - 20,))
    con.commit()
    return run_summary(rid)


def _summary(out, lines, s):
    cats = {c: dict(n=0, credit=0.0, debit=0.0, marking=0) for c in CATS}
    for o in out:
        c = cats[o["cat"]]
        c["n"] += 1
        c["credit"] = round(c["credit"] + o["credit"], 2)
        c["debit"] = round(c["debit"] + o["debit"], 2)
        c["marking"] += o["action"] == "mark"
    ignore = {t.upper() for t in s["ignore_doc_types"]}
    vmap = {v["pv"]: v for v in rows("SELECT * FROM pm_vouchers")}
    vouchers = OrderedDict()
    for l in lines:
        v = vouchers.setdefault(l["pv"], dict(pv=l["pv"], pv_date=l["pv_date"], amount=(vmap.get(l["pv"]) or {}).get("amount"),
                                              credit=0.0, debit=0.0, discount=0.0, lines=0))
        v["credit"] += l["credit"]
        v["debit"] += l["debit"]
        v["lines"] += 1
        if l["doc_type"] in ignore:
            v["discount"] += l["debit"]
    for v in vouchers.values():
        v["credit"], v["debit"], v["discount"] = round(v["credit"], 2), round(v["debit"], 2), round(v["discount"], 2)
        v["net"] = round(v["credit"] - v["debit"], 2)
        v["tallies"] = v["amount"] is not None and abs(v["net"] - v["amount"]) < 0.05
    return dict(cats=cats, vouchers=list(vouchers.values()), invoices=len(out),
                to_mark=sum(1 for o in out if o["action"] == "mark"),
                mark_value=round(sum(o["credit"] for o in out if o["action"] == "mark"), 2))


def run_summary(rid):
    run = one("SELECT * FROM pm_runs WHERE id=?", (rid,))
    if not run:
        return None
    run["summary"] = json.loads(run["summary"])
    # 'marking' counts change when lines are ticked / unticked
    for r in rows("SELECT cat, SUM(action='mark') n FROM pm_run_lines WHERE run_id=? GROUP BY cat", (rid,)):
        run["summary"]["cats"][r["cat"]]["marking"] = r["n"]
    t = one("SELECT COUNT(*) n, COALESCE(SUM(credit),0) v FROM pm_run_lines WHERE run_id=? AND action='mark'", (rid,))
    run["summary"]["to_mark"], run["summary"]["mark_value"] = t["n"], round(t["v"], 2)
    f = one("SELECT name FROM pm_files WHERE id=?", (run["register_file"],))
    run["register_name"] = f["name"] if f else ""
    return run
