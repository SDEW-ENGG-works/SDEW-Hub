"""Files dropped on the GRIN & Payments page.

  TAFE 'Payment Clearance Details' export (.xls)   -> gp_pay_lines   (added; same line twice = kept once)
  SDEW invoice register (INVOICE NO ... payment details) -> gp_register (replaced: the register is the whole year)
  Tally XML (Day Book / vouchers exported from Tally)    -> gp_tally_*  (same as the live pull)
  TAFE GRIN Details / Tally Sales Register / TAFE PO     -> handed to the Supplementary Bill importer (shared data)
"""
import os
import re
from datetime import datetime

from ... import config
from ...http import ApiError
from ..db import get_db, log, rows
from . import payments, status, tally
from .defaults import plants


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _save(name, data):
    d = config.upload_dir("grin")
    safe = re.sub(r"[^\w.\- ]", "_", os.path.basename(name or "upload"))
    stored = f"{datetime.now():%Y%m%d_%H%M%S_%f}_{safe}"
    path = os.path.join(d, stored)
    with open(path, "wb") as fh:
        fh.write(data)
    return stored, path


def ingest(name, data):
    stored, path = _save(name, data)
    try:
        res = _ingest(name, data, stored, path)
    finally:
        status.invalidate()
    return res


def _ingest(name, data, stored, path):
    is_excel = data[:2] == b"PK" or data[:4] == b"\xd0\xcf\x11\xe0"
    if is_excel:
        try:
            if payments.is_payment_export(path):
                return store_payments(name, stored, path)
            if payments.is_register(path):
                return store_register(name, stored, path)
        except ApiError:
            raise
        except Exception:  # noqa: BLE001 - not ours, let the Supplementary Bill importer try
            pass
    head = data[:3000].decode("utf-8", errors="ignore").upper() + data[:3000].decode("utf-16-le", errors="ignore").upper()
    if "<ENVELOPE" in head or "<VOUCHER" in head or "TALLYMESSAGE" in head:
        return store_tally_xml(name, data)
    from ...supp.services.ingest import ingest as supp_ingest
    try:
        r = supp_ingest(name, data)
    except ApiError as e:
        raise ApiError(f"{name}: not recognised. Drop a TAFE Payment Clearance export, the invoice register "
                       f"(INVOICE NO ... payment details), a Tally XML export, a TAFE GRIN Details export or the "
                       f"Tally Sales Register.") from e
    r = dict(r)
    r["message"] = f"{r.get('message', '')} (stored with the Supplementary Bill data)".strip()
    return r


def _write_many(con, sql_head, rows_, per=40):
    """Many rows per INSERT and a commit every ~1,000 rows: small, few requests when the database is Turso."""
    if not rows_:
        return
    ph = "(" + ",".join("?" * len(rows_[0])) + ")"
    for k in range(0, len(rows_), per):
        chunk = rows_[k:k + per]
        con.execute(sql_head + " VALUES " + ",".join([ph] * len(chunk)), [v for r in chunk for v in r])
        if (k // per) % 25 == 24:
            con.commit()


def store_payments(name, stored, path):
    """Only lines not in the database yet (or changed) are written - a payment export loaded again costs nothing."""
    p = payments.read_payments(path)
    con = get_db()
    now = _now()
    pvs = sorted({ln["pv"] for ln in p["lines"]})
    have = {}
    if pvs:
        for r in rows(f"SELECT pv, ref_doc, inv_key, pv_date, debit, credit FROM gp_pay_lines WHERE pv IN "
                      f"({','.join('?' * len(pvs))})", pvs):
            have[(r["pv"], r["ref_doc"], r["inv_key"])] = (r["pv_date"], r["debit"], r["credit"])
    new = [ln for ln in p["lines"]
           if have.get((ln["pv"], ln["ref_doc"], ln["inv_key"])) != (ln["pv_date"], ln["debit"], ln["credit"])]
    added = sum(1 for ln in new if (ln["pv"], ln["ref_doc"], ln["inv_key"]) not in have)
    _write_many(con, "INSERT OR REPLACE INTO gp_pay_lines(pv, pv_date, ref_doc, doc_type, inv_raw, inv_key, inv_date, "
                     "debit, credit, file, loaded_at)",
                [(ln["pv"], ln["pv_date"], ln["ref_doc"], ln["doc_type"], ln["inv_raw"], ln["inv_key"], ln["inv_date"],
                  ln["debit"], ln["credit"], name, now) for ln in new])
    con.execute("INSERT INTO gp_pay_files(kind, name, stored, period_from, period_to, rows, loaded_at) "
                "VALUES('Payments',?,?,?,?,?,?)", (name, stored, p["period_from"], p["period_to"], len(p["lines"]), now))
    con.commit()
    log("grin", "Payment export", f"{name}: {len(p['vouchers'])} vouchers, {len(p['lines'])} lines")
    return dict(kind="Payments", message=f"TAFE payments {p['period_from']} to {p['period_to']}: "
                f"{len(p['vouchers'])} vouchers, {len(p['lines'])} lines ({added} new)", rows=len(p["lines"]))


REG_COLS = ("inv_no", "inv_date", "amount", "party", "pv", "pv_date", "cancelled")


def store_register(name, stored, path):
    """The register is the whole year (13,000+ invoices). Only invoices that are new or changed (e.g. newly
    marked paid) are written; the rest of gp_register is left as it is - a few KB instead of ~8 MB to Turso."""
    reg = payments.read_register(path)
    con = get_db()
    now = _now()
    want = {}
    for r in reg["rows"]:
        k = r["inv_key"]
        if k in want:                 # the same invoice twice: keep the first row, with the mark of any copy
            if r["pv"] and not want[k]["pv"]:
                want[k] = dict(want[k], pv=r["pv"], pv_date=r["pv_date"])
            continue
        want[k] = r
    have = {x["inv_key"]: x for x in rows("SELECT inv_key, " + ", ".join(REG_COLS) + " FROM gp_register")}

    def same(a, b):
        for c in REG_COLS:
            x, y = a.get(c), b.get(c)
            if c == "amount":
                if round(float(x or 0), 2) != round(float(y or 0), 2):
                    return False
            elif c == "cancelled":
                if int(x or 0) != int(y or 0):
                    return False
            elif (x or "") != (y or ""):
                return False
        return True

    changed = [r for k, r in want.items() if k not in have or not same(r, have[k])]
    gone = [k for k in have if k not in want]
    for i in range(0, len(gone), 200):
        part = gone[i:i + 200]
        con.execute(f"DELETE FROM gp_register WHERE inv_key IN ({','.join('?' * len(part))})", part)
    _write_many(con, "INSERT OR REPLACE INTO gp_register(inv_key, inv_no, inv_date, amount, party, pv, pv_date, "
                     "cancelled, file, loaded_at)",
                [(r["inv_key"], r["inv_no"], r["inv_date"], r["amount"], r["party"], r["pv"], r["pv_date"],
                  r["cancelled"], name, now) for r in changed])
    con.execute("UPDATE gp_register SET file=?, loaded_at=?", (name, now))
    con.execute("INSERT INTO gp_pay_files(kind, name, stored, period_from, period_to, rows, loaded_at) "
                "VALUES('Register',?,?,?,?,?,?)",
                (name, stored, min((r["inv_date"] for r in reg["rows"] if r["inv_date"]), default=""),
                 max((r["inv_date"] for r in reg["rows"] if r["inv_date"]), default=""), len(reg["rows"]), now))
    con.commit()
    marked = sum(1 for r in reg["rows"] if r["pv"])
    log("grin", "Invoice register", f"{name}: {len(reg['rows'])} invoices, {marked} marked paid "
        f"({len(changed)} new/changed, {len(gone)} removed)")
    return dict(kind="Register", message=f"Invoice register ({reg['sheet']}): {len(reg['rows'])} invoices, "
                f"{marked} marked paid", rows=len(reg["rows"]))


def store_tally_xml(name, data):
    text = tally.decode(data)
    try:
        invs = tally.parse_vouchers(text)
    except Exception as e:  # noqa: BLE001
        raise ApiError(f"{name}: Tally XML could not be read ({e})")
    parties = {p["party"] for p in plants()}
    keep = [i for i in invs if tally.is_sales(i, parties)]
    tally.store(keep, "", source=f"Tally XML file {name}")
    log("grin", "Tally XML file", f"{name}: {len(keep)} TAFE invoices")
    return dict(kind="Tally", message=f"Tally XML: {len(invs)} vouchers, {len(keep)} TAFE sales invoices", rows=len(keep))
