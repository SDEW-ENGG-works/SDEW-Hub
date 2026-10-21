"""Uploads (recognised by their contents) and saving made files."""
import csv
import io
import json
import re
from datetime import datetime

from ..db import get_db, get_setting, one, rows, set_setting
from ..http import ApiError
from . import builder, dqms_report, dr_pdf, invoice_pdf, po
from .defaults import DEFAULT_SETTINGS, load_settings


def _now():
    return datetime.now().isoformat(timespec="seconds")


def ingest(name, data):
    low = name.lower()
    if data[:5] == b"%PDF-" or low.endswith(".pdf"):
        try:
            is_dr = dr_pdf.looks_like_dr(dr_pdf.first_page_text(data))
        except Exception:  # noqa: BLE001
            is_dr = False
        return _drs(name, data) if is_dr else _invoices(name, data)
    if low.endswith((".htm", ".html")) or data[:200].lstrip().lower().startswith((b"<html", b"<!doctype")):
        r = po.import_htm(name, data)
        if r:
            return r
        raise ApiError(f"{name}: this web page is not a TAFE purchase order.")
    if low.endswith(".csv"):
        return _csv(name, data)
    if low.endswith((".xls", ".xlsx", ".xlsm")):
        try:
            table = dqms_report.read_rows(name, data)
        except Exception as e:  # noqa: BLE001
            raise ApiError(f"{name}: could not read the workbook ({e})")
        if not dqms_report.looks_like_report(table):
            raise ApiError(f"{name}: not a DQMS Batch Details report (no Batch Number / Batch Balance columns).")
        return _report(name, table)
    raise ApiError(f"{name}: unknown file. Drop invoice PDFs, the DQMS Batch Details report (.xls), "
                   "a PO (.htm) or the portal's status file (.csv).")


def _invoices(name, data):
    try:
        invs, warns = invoice_pdf.parse_pdf(data)
    except Exception as e:  # noqa: BLE001
        raise ApiError(f"{name}: could not read the PDF ({e})")
    if not invs:
        raise ApiError(f"{name}: no invoice found in this PDF (is it a scanned image?)")
    con = get_db()
    new, updated = [], []
    for inv in invs:
        old = one("SELECT inv_no, edits, run_id FROM invoices WHERE inv_no=?", (inv["inv_no"],))
        t = inv["taxes"]
        con.execute(
            "INSERT INTO invoices(inv_no,inv_date,order_no,total,cgst,sgst,igst,packages,drs,items,consignee,warnings,"
            "edits,file_name,uploaded_at,run_id,eway,unit_size) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(inv_no) DO UPDATE SET inv_date=excluded.inv_date, order_no=excluded.order_no, total=excluded.total, "
            "cgst=excluded.cgst, sgst=excluded.sgst, igst=excluded.igst, packages=excluded.packages, drs=excluded.drs, "
            "items=excluded.items, consignee=excluded.consignee, warnings=excluded.warnings, file_name=excluded.file_name, "
            "uploaded_at=excluded.uploaded_at, eway=excluded.eway, unit_size=excluded.unit_size",
            (inv["inv_no"], inv["inv_date"], inv["order_no"], inv["total"], t.get("cgst"), t.get("sgst"),
             (t.get("igst") or 0) + (t.get("utgst") or 0) or None, inv["packages"], json.dumps(inv["drs"]),
             json.dumps(inv["items"]), inv["consignee"], json.dumps(inv["warnings"]),
             old["edits"] if old else "{}", name, _now(), old["run_id"] if old else None, inv.get("eway") or "", inv.get("unit_size")))
        (updated if old else new).append(inv["inv_no"])
    con.commit()
    return dict(kind="invoices", file=name, new=new, updated=updated, warnings=warns)


def _drs(name, data):
    try:
        rows = dr_pdf.parse_pdf(data)
    except Exception as e:  # noqa: BLE001
        raise ApiError(f"{name}: could not read the Delivery Request PDF ({e})")
    if not rows:
        raise ApiError(f"{name}: Delivery Request found but no part line could be read.")
    con = get_db()
    for r in rows:
        con.execute("INSERT OR REPLACE INTO delivery_requests(dr_no,part,order_no,descr,bin,req,size,qty,file_name,uploaded_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (r["dr_no"], r["part"], r["order_no"], r["descr"], r["bin"], r["req"], r["size"], r["qty"], name, _now()))
    con.commit()
    return dict(kind="drs", drs=sorted({r["dr_no"] for r in rows}), lines=len(rows))


def _report(name, table):
    try:
        batches = dqms_report.parse(table)
    except ValueError as e:
        raise ApiError(f"{name}: {e}")
    con = get_db()
    con.execute("DELETE FROM dqms_batches")
    for b in batches:
        con.execute("INSERT OR REPLACE INTO dqms_batches(batch_no,part,descr,total,consumed,balance,created) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (b["batch_no"], b["part"], b["descr"], b["total"], b["consumed"], b["balance"], b["created"]))
    con.commit()
    info = dict(name=name, uploaded_at=_now(), report_time=dqms_report.time_from_name(name) or _now(),
                batches=len(batches), parts=len({b["part"] for b in batches}),
                with_balance=sum(1 for b in batches if b["balance"] > 0))
    set_setting("dqms_report", info)
    return dict(kind="report", **info)


def _csv(name, data):
    text = data.decode("utf-8-sig", errors="ignore")
    table = list(csv.reader(io.StringIO(text)))
    if not table or not table[0] or not table[0][0].strip().lower().startswith("record flag"):
        raise ApiError(f"{name}: not a DQMS template (first column must be 'Record Flag*').")
    head = [h.strip() for h in table[0]]
    low = [h.lower() for h in head]
    if "upload status" in low:
        return _status(name, head, low, table[1:])
    # a blank template from TAFE Channel: keep its column headings
    header = head
    while header and not header[-1]:
        header.pop()
    if len(header) != len(DEFAULT_SETTINGS["header"]):
        raise ApiError(f"{name}: the template has {len(header)} columns, the app expects "
                       f"{len(DEFAULT_SETTINGS['header'])}. Ask for the app to be updated.")
    s = get_setting("app") or {}
    s["header"] = header
    set_setting("app", s)
    return dict(kind="template", columns=len(header))


def _status(name, head, low, body):
    ci = {k: low.index(k) for k in low if k}
    get = lambda r, k: r[ci[k]].strip() if k in ci and ci[k] < len(r) else ""  # noqa: E731
    con = get_db()
    cur, seq, seen, ok, bad = None, 0, set(), 0, 0
    for r in body:
        if not any(c.strip() for c in r):
            continue
        flag = get(r, "record flag*")
        if flag == "INVOICE_LR_DTLS":
            cur = get(r, "invoice no.*")
            seq = 0
            if cur and cur not in seen:
                con.execute("DELETE FROM portal_status WHERE inv_no=?", (cur,))
                seen.add(cur)
        if not cur:
            continue
        seq += 1
        status = get(r, "upload status")
        msg = get(r, "validation message")
        # the portal sometimes spills the message into the next columns
        extra = [c.strip() for c in r[ci.get("validation message", len(r)) + 1:] if c.strip()]
        if extra:
            msg = ", ".join([msg] + extra) if msg else ", ".join(extra)
        con.execute("INSERT OR REPLACE INTO portal_status(inv_no,seq,record,part,batch_no,status,message,file_name,uploaded_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (cur, seq, flag, get(r, "part no.*"), get(r, "batch no."), status, msg, name, _now()))
        if status.upper() == "SUCCESS":
            ok += 1
        else:
            bad += 1
    con.commit()
    return dict(kind="status", invoices=len(seen), ok_rows=ok, failed_rows=bad)


def save_edits(inv_no, edits):
    r = one("SELECT edits FROM invoices WHERE inv_no=?", (inv_no,))
    if not r:
        raise ApiError("Invoice not found", 404)
    cur = json.loads(r["edits"] or "{}")
    for k in ("dr", "reason", "remarks", "unit", "eway"):
        if k in edits:
            v = str(edits[k] if edits[k] is not None else "").strip()
            if v:
                cur[k] = v
            else:
                cur.pop(k, None)
    con = get_db()
    con.execute("UPDATE invoices SET edits=? WHERE inv_no=?", (json.dumps(cur), inv_no))
    con.commit()
    return cur


def generate(selected, edits):
    for no, e in (edits or {}).items():
        if one("SELECT 1 x FROM invoices WHERE inv_no=?", (no,)):
            save_edits(no, e)
    res = builder.build(selected)
    s = res["summary"]
    if not s["invoices"]:
        raise ApiError("Tick at least one invoice.")
    if s["blocked"]:
        raise ApiError(f"{s['blocked']} line(s) still need attention (red rows).")
    data = builder.to_csv(res["header"], res["rows"])
    st = load_settings()
    dates = sorted({ln["inv_date"] for ln in res["lines"] if ln["selected"] and not ln.get("deferred") and ln["inv_date"]})
    tag = builder.dmy(dates[-1]).replace(".", "-") if dates else datetime.now().strftime("%d-%m-%Y")
    fname = st["file_name"].replace("{date}", tag)
    # TAFE Channel is picky about upload names: no spaces, one dot, ".csv" at the end
    base = re.sub(r"\.csv$", "", fname.strip(), flags=re.I)
    base = re.sub(r"[^A-Za-z0-9_\-]+", "_", base).strip("_.") or "template"
    fname = base + ".csv"
    invs = sorted({ln["inv_no"] for ln in res["lines"] if ln["selected"] and not ln.get("deferred")}, key=builder.inv_sort_key)
    summary = dict(invoices=s["invoices"], items=s["items"], rows=s["rows"], value=s["value"],
                   batch_rows=sum(1 for r in res["rows"] if r["kind"] == "batch"),
                   first=invs[0], last=invs[-1], report=(res["report"] or {}).get("name", ""))
    con = get_db()
    cur = con.execute("INSERT INTO dqms_runs(created_at,file_name,summary,rows,invoices,csv) VALUES(?,?,?,?,?,?)",
                      (_now(), fname, json.dumps(summary), json.dumps([r["cells"] for r in res["rows"]]),
                       json.dumps(invs), data))
    run_id = cur.lastrowid
    for no in invs:
        con.execute("UPDATE invoices SET run_id=? WHERE inv_no=?", (run_id, no))
    con.commit()
    return dict(run_id=run_id, file_name=fname, summary=summary)


def counts():
    return dict(invoices=one("SELECT COUNT(*) n FROM invoices")["n"],
                pending=one("SELECT COUNT(*) n FROM invoices WHERE run_id IS NULL")["n"],
                runs=one("SELECT COUNT(*) n FROM dqms_runs")["n"],
                drs=one("SELECT COUNT(DISTINCT dr_no) n FROM delivery_requests")["n"],
                pos=one("SELECT COUNT(*) n FROM po_headers")["n"],
                po_items=one("SELECT COUNT(*) n FROM po_items")["n"])


def report_summary():
    return builder.report_info()


def remove_invoice(inv_no):
    con = get_db()
    con.execute("DELETE FROM invoices WHERE inv_no=?", (inv_no,))
    con.execute("DELETE FROM portal_status WHERE inv_no=?", (inv_no,))
    con.commit()
    return dict(ok=True)


def list_invoices():
    return rows("SELECT inv_no, inv_date, order_no, total, run_id, file_name, uploaded_at FROM invoices")
