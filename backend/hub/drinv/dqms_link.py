"""DR -> Invoice  <->  DQMS Upload: one set of DRs and invoices for both.

- DRs uploaded on DR -> Invoice go into DQMS's Delivery Request list (delivery_requests) too, exactly as a DR
  dropped on the DQMS page - so staff upload each DR once.
- Every invoice sent to Tally from DR -> Invoice goes into DQMS's invoices (as a dropped invoice PDF would):
  number, date, PO, total, CGST/SGST/IGST, packages, unit size (pieces), DR, part line (qty, rate, amount),
  consignee - so DQMS needs neither the DR PDF nor the invoice PDF for them.
- When Tally gave another number, or an invoice is taken back from Tally, DQMS follows.
On the website DQMS keeps its own database (the old DQMS website's); dqms.db picks the right one.
A DQMS invoice that was uploaded as a PDF or is already in a DQMS run is never overwritten.
"""
import json
from datetime import datetime

SOURCE = "DR → Invoice (hub)"


def _db():
    from ..dqms import db as qdb
    return qdb


def _now():
    return datetime.now().isoformat(timespec="seconds")


def push_drs(lines, file_name):
    """DR lines (dr_pdf.parse_pdf) -> DQMS delivery_requests."""
    try:
        q = _db()
        con = q.get_db()
        for r in lines:
            con.execute("INSERT OR REPLACE INTO delivery_requests(dr_no,part,order_no,descr,bin,req,size,qty,file_name,"
                        "uploaded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (r["dr_no"], r["part"], r["order_no"], r["descr"], r["bin"], r["req"], r["size"], r["qty"],
                         file_name, _now()))
        con.commit()
        return len(lines)
    except Exception as e:  # noqa: BLE001  (DQMS never stops an invoice)
        print("[DR->Invoice] DQMS DRs not saved:", e)
        return 0


def _consignee(d, cfg):
    pl = (cfg.get("plants") or {}).get(d.get("plant") or "", {})
    return " ".join([pl.get("party", "")] + list(pl.get("address") or []))[:200]


def push_invoice(d, cfg):
    """One invoice sent to Tally -> DQMS invoices (skipped when DQMS has it from a PDF or in a run)."""
    if not d.get("inv_no"):
        return False
    try:
        q = _db()
        con = q.get_db()
        old = q.one("SELECT inv_no, edits, run_id, file_name FROM invoices WHERE inv_no=?", (d["inv_no"],))
        if old and (old.get("run_id") or (old.get("file_name") or "") != SOURCE):
            return False
        items = [dict(sl=1, part=d["part"], descr=d.get("descr") or d.get("item_name") or "", hsn="",
                      qty=float(d.get("qty") or 0), uom=cfg.get("unit") or "QTY", rate=float(d.get("rate") or 0),
                      amount=float(d.get("amount") or 0))]
        con.execute(
            "INSERT INTO invoices(inv_no,inv_date,order_no,total,cgst,sgst,igst,packages,drs,items,consignee,warnings,"
            "edits,file_name,uploaded_at,run_id,eway,unit_size) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(inv_no) DO UPDATE SET inv_date=excluded.inv_date, order_no=excluded.order_no, total=excluded.total, "
            "cgst=excluded.cgst, sgst=excluded.sgst, igst=excluded.igst, packages=excluded.packages, drs=excluded.drs, "
            "items=excluded.items, consignee=excluded.consignee, warnings=excluded.warnings, file_name=excluded.file_name, "
            "uploaded_at=excluded.uploaded_at, unit_size=excluded.unit_size",
            (d["inv_no"], d["inv_date"], d["po_no"], d.get("total"), d.get("cgst") or None, d.get("sgst") or None,
             d.get("igst") or None, int(float(d["packages"])) if d.get("packages") else None,
             json.dumps([d["dr_no"]]), json.dumps(items), _consignee(d, cfg), json.dumps([]),
             old["edits"] if old else "{}", SOURCE, _now(), None, "",
             float(d["pieces"]) if d.get("pieces") else None))
        con.commit()
        return True
    except Exception as e:  # noqa: BLE001
        print("[DR->Invoice] DQMS invoice not saved:", e)
        return False


def remove_invoice(inv_no):
    """Taken back from Tally / renumbered: drop the copy DR -> Invoice made (never a PDF upload or a run's)."""
    if not inv_no:
        return
    try:
        q = _db()
        con = q.get_db()
        con.execute("DELETE FROM invoices WHERE inv_no=? AND file_name=? AND run_id IS NULL", (inv_no, SOURCE))
        con.commit()
    except Exception as e:  # noqa: BLE001
        print("[DR->Invoice] DQMS invoice not removed:", e)


def sync_all(drafts, cfg):
    """Every sent invoice -> DQMS, every draft's DR -> DQMS's DR list. -> counts."""
    n_inv = sum(1 for d in drafts if d.get("status") == "sent" and push_invoice(d, cfg))
    seen, lines = set(), []
    for d in drafts:
        k = (d["dr_no"], d["part"])
        if k not in seen:
            seen.add(k)
            lines.append(dict(dr_no=d["dr_no"], part=d["part"], order_no=d["po_no"], descr=d.get("descr") or "",
                              bin=d.get("bin") or "", req=d.get("dr_req"), size=d.get("dr_size"), qty=d.get("dr_qty")))
    n_dr = 0
    try:
        q = _db()
        have = {(r["dr_no"], r["part"]) for r in q.rows("SELECT dr_no, part FROM delivery_requests")}
        new = [x for x in lines if (x["dr_no"], x["part"]) not in have]
        n_dr = push_drs(new, SOURCE) if new else 0
    except Exception as e:  # noqa: BLE001
        print("[DR->Invoice] DQMS DR sync:", e)
    return dict(invoices=n_inv, drs=n_dr)
