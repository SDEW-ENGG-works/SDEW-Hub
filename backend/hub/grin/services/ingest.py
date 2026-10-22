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
from ..db import get_db, log
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


def store_payments(name, stored, path):
    p = payments.read_payments(path)
    con = get_db()
    now = _now()
    before = con.execute("SELECT COUNT(*) FROM gp_pay_lines").fetchone()[0]
    for ln in p["lines"]:
        con.execute("INSERT OR REPLACE INTO gp_pay_lines(pv, pv_date, ref_doc, doc_type, inv_raw, inv_key, inv_date, "
                    "debit, credit, file, loaded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (ln["pv"], ln["pv_date"], ln["ref_doc"], ln["doc_type"], ln["inv_raw"], ln["inv_key"], ln["inv_date"],
                     ln["debit"], ln["credit"], name, now))
    con.execute("INSERT INTO gp_pay_files(kind, name, stored, period_from, period_to, rows, loaded_at) "
                "VALUES('Payments',?,?,?,?,?,?)", (name, stored, p["period_from"], p["period_to"], len(p["lines"]), now))
    con.commit()
    added = con.execute("SELECT COUNT(*) FROM gp_pay_lines").fetchone()[0] - before
    log("grin", "Payment export", f"{name}: {len(p['vouchers'])} vouchers, {len(p['lines'])} lines")
    return dict(kind="Payments", message=f"TAFE payments {p['period_from']} to {p['period_to']}: "
                f"{len(p['vouchers'])} vouchers, {len(p['lines'])} lines ({added} new)", rows=len(p["lines"]))


def store_register(name, stored, path):
    reg = payments.read_register(path)
    con = get_db()
    now = _now()
    con.execute("DELETE FROM gp_register")
    seen = set()
    for k, r in enumerate(reg["rows"]):
        if k and k % 2000 == 0:
            con.commit()          # Turso: send the rows in parts, not one huge request
        if r["inv_key"] in seen:      # the same invoice twice: keep the marked / first row
            if r["pv"]:
                con.execute("UPDATE gp_register SET pv=?, pv_date=? WHERE inv_key=? AND (pv IS NULL OR pv='')",
                            (r["pv"], r["pv_date"], r["inv_key"]))
            continue
        seen.add(r["inv_key"])
        con.execute("INSERT INTO gp_register(inv_key, inv_no, inv_date, amount, party, pv, pv_date, cancelled, file, "
                    "loaded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (r["inv_key"], r["inv_no"], r["inv_date"], r["amount"], r["party"], r["pv"], r["pv_date"],
                     r["cancelled"], name, now))
    con.execute("INSERT INTO gp_pay_files(kind, name, stored, period_from, period_to, rows, loaded_at) "
                "VALUES('Register',?,?,?,?,?,?)",
                (name, stored, min((r["inv_date"] for r in reg["rows"] if r["inv_date"]), default=""),
                 max((r["inv_date"] for r in reg["rows"] if r["inv_date"]), default=""), len(reg["rows"]), now))
    con.commit()
    marked = sum(1 for r in reg["rows"] if r["pv"])
    log("grin", "Invoice register", f"{name}: {len(reg['rows'])} invoices, {marked} marked paid")
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
