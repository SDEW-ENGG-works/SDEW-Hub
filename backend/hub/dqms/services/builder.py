"""Invoices + DQMS batch report + PO line items -> rows of TAFE's DQMS bulk upload template.

For every invoice item:
    INVOICE_LR_DTLS row   DR, Order, PO line item, part, reason for gap, invoice no/date,
                          invoice unit (= qty / Unit Size printed on the invoice, else the DR PDF's; No of Packeges when neither), final value, CGST/SGST/IGST, transporter
    BATCH_DTLS row(s)     batch no + qty to consume, taken from the DQMS report: oldest batch
                          with balance first; when one batch is not enough the rest comes from
                          the next batch (one BATCH_DTLS row per batch). Batches used by an
                          earlier invoice in the same file are reduced first.
"""
import csv
import io
import json
import re

from ..db import get_setting, rows
from . import po
from .defaults import load_settings

COLS = {name: i for i, name in enumerate([
    "flag", "dr", "order", "line", "part", "reason", "remarks", "inv_no", "inv_date", "unit", "value",
    "cgst", "sgst", "igst", "eway", "eway_from", "eway_to", "transporter", "lr", "lr_date", "packages",
    "kgs", "vehicle_type", "vehicle", "start", "batch_app", "batch_no", "batch_qty", "batch_cons", "batch_rem"])}


def fmt(v):
    """13145.0 -> '13145', 7699.5 -> '7699.5', 384.98 -> '384.98'"""
    if v is None or v == "":
        return ""
    v = round(float(v), 2)
    return str(int(v)) if v == int(v) else f"{v:.2f}".rstrip("0")


def dmy(iso):
    return f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}" if iso and len(iso) >= 10 else ""


def inv_sort_key(no):
    m = re.match(r"(\d+)", no or "")
    return (no.split("/")[-1] if "/" in (no or "") else "", int(m.group(1)) if m else 0, no)


def _one_digit_off(a, b):
    """True when a and b differ by one digit missing, extra or changed (a Tally typing slip)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    s, l = (a, b) if len(a) < len(b) else (b, a)
    return any(l[:i] + l[i + 1:] == s for i in range(len(l)))


def load_invoices(inv_nos=None):
    out = []
    for r in rows("SELECT * FROM invoices"):
        if inv_nos is not None and r["inv_no"] not in inv_nos:
            continue
        for k in ("drs", "items", "warnings", "edits"):
            r[k] = json.loads(r[k] or ("{}" if k == "edits" else "[]"))
        out.append(r)
    out.sort(key=lambda r: inv_sort_key(r["inv_no"]))
    return out


def portal_messages():
    msgs = {}
    for r in rows("SELECT inv_no, seq, record, part, batch_no, status, message, file_name, uploaded_at "
                  "FROM portal_status ORDER BY inv_no, seq"):
        msgs.setdefault(r["inv_no"], []).append(r)
    return msgs


def report_info():
    return get_setting("dqms_report") or {}


def build(selected, edits_in=None):
    """selected: invoice numbers to put in the file (in invoice-number order).
    edits_in: {inv_no: {dr, reason, remarks, unit}} not yet saved (the page sends what is on screen)."""
    st = load_settings()
    items_map, overrides, parts_map, plants = po.lookup_maps()
    invs = load_invoices()
    # nothing chosen yet (page just opened): tick every invoice not yet put in a file
    sel = set(selected) if selected is not None else {i["inv_no"] for i in invs if not i["run_id"]}
    msgs = portal_messages()
    edits_in = edits_in or {}

    batches = {}
    for b in rows("SELECT batch_no, part, descr, total, consumed, balance, created FROM dqms_batches"):
        batches.setdefault(b["part"], []).append(b)
    newest_first = st.get("batch_order") == "newest"
    for lst in batches.values():
        lst.sort(key=lambda b: (b["created"] or "", b["batch_no"]), reverse=newest_first)
    left = {b["batch_no"]: b["balance"] for lst in batches.values() for b in lst}
    start = dict(left)   # what the portal sees: it checks every invoice against the balance at the start of the upload

    drmap = {(r["dr_no"], r["part"]): r for r in rows("SELECT * FROM delivery_requests")}
    lines, out_rows, warnings = [], [], []
    summary = dict(invoices=0, items=0, rows=0, blocked=0, value=0.0, in_file=0, total_invoices=len(invs))
    for inv in invs:
        ed = dict(inv["edits"])
        ed.update(edits_in.get(inv["inv_no"], {}))
        chosen = inv["inv_no"] in sel
        dr = (ed.get("dr") or (inv["drs"][0] if len(inv["drs"]) == 1 else "")).strip()
        unit_typed = ed.get("unit") not in (None, "")
        if unit_typed:
            unit0 = ed.get("unit")
        else:
            unit0 = 1 if st.get("invoice_unit") == "one" else inv["packages"]
        inv_size = inv.get("unit_size") or None
        # No "Unit Size" on the invoice: alert and leave it out of the file (a hand-typed Invoice Unit brings it back)
        nosize = not inv_size and not unit_typed
        # Buyer's Order No. typed wrong in Tally (e.g. 103000676 for 1030000676): match it to a known PO
        order, order_note = inv["order_no"], ""
        if order and order not in plants and not any(k[0] == order for k in items_map):
            near = sorted({po_no for po_no in plants if _one_digit_off(order, po_no)})
            if len(near) == 1:
                order_note = f"Buyer's Order No. on the invoice is {order} - taken as PO {near[0]}. Correct it in Tally."
                order = near[0]
            else:
                order_note = f"Buyer's Order No. {order} is not a known PO - check it in Tally"
        reason = ed.get("reason") or ""
        remarks = ed.get("remarks") or ""
        eway = re.sub(r"\s", "", ed.get("eway") or inv.get("eway") or "")
        pmsgs = msgs.get(inv["inv_no"], [])
        multi = len(inv["items"]) > 1
        for it in inv["items"] or [dict(part="", descr="", qty=0, amount=0)]:
            key = f"{inv['inv_no']}|{it['part']}"
            problems, notes = [], list(inv["warnings"])
            if multi:
                notes.append(f"Invoice has {len(inv['items'])} parts - one invoice row per part, each with the full invoice value. Check before uploading.")
            if order_note:
                notes.append(order_note)
            # PO line item
            line, line_src = None, ""
            if (order, it["part"]) in overrides:
                line, line_src = overrides[(order, it["part"])], "typed"
            elif (order, it["part"]) in items_map:
                line, line_src = items_map[(order, it["part"])]["item"], "PO"
            else:
                line_src = "missing"
                other = [f"{r['po_no']} line {r['item']}" for r in parts_map.get(it["part"], [])]
                problems.append(f"Part {it['part']} not found in PO {order or '?'}" +
                                (f" (it is in {', '.join(other[:3])})" if other else "") + " - type the line item")
            if not dr:
                problems.append("DR No. missing - type it" if not inv["drs"] else
                                f"Several DRs on the invoice ({', '.join(inv['drs'])}) - choose one")
            elif not ed.get("dr") and len(dr) != 8:
                problems.append(f"DR {dr} on the invoice has {len(dr)} digits (DR numbers have 8) - check it and retype")
            if not order:
                problems.append("Order No. not found on the invoice")
            if (inv["total"] or 0) > 50000 and not re.fullmatch(r"\d{12}", eway):
                problems.append("Value above 50,000 - the portal needs the 12-digit E-way Bill No. - type it" if not eway
                                else f"E-way Bill No. {eway} must be 12 digits")
            # Invoice Unit = invoice qty / Unit Size (bins as TAFE counts them). The Unit Size printed on the
            # invoice comes first; a loaded DR PDF is used when the invoice has none, and to cross-check.
            unit, unit_src, drrow = unit0, ("typed" if unit_typed else "packages"), drmap.get((dr, it["part"]))
            qty_ = float(it.get("qty") or 0)
            size, size_src = (inv_size, "invoice") if inv_size else ((drrow["size"], "DR") if drrow and drrow["size"] else (None, ""))
            if size and not unit_typed:
                n = qty_ / size
                if abs(n - round(n)) < 1e-6:
                    unit, unit_src = int(round(n)), size_src
                else:
                    problems.append(f"Qty {fmt(qty_)} is not a whole number of bins of {fmt(size)} "
                                    f"({'Unit Size on the invoice' if size_src == 'invoice' else 'DR ' + dr}) - type the Invoice Unit")
            if inv_size and drrow and drrow["size"] and abs(inv_size - drrow["size"]) > 1e-6:
                problems.append(f"Unit Size on the invoice is {fmt(inv_size)} but DR {dr} says {fmt(drrow['size'])} - "
                                "correct the invoice or type the Invoice Unit")
            if drrow:
                notes.append(f"DR {dr}: {drrow['req']} x {fmt(drrow['size'])} = {fmt(drrow['qty'])} in {drrow['bin']}")
                if abs(qty_ - drrow["qty"]) > 1e-6 and not reason:
                    problems.append(f"Invoice qty {fmt(qty_)} differs from the DR qty {fmt(drrow['qty'])} - choose a Reason for Gap "
                                    f"({'EXTRA PULL BY TAFE' if qty_ > drrow['qty'] else 'e.g. FG NOT AVAILABLE'})")
            elif chosen and dr and not unit_typed and not inv_size:
                notes.append(f"No Unit Size on the invoice and DR {dr} PDF not loaded - Invoice Unit taken from 'No of Packeges'")
            if unit in (None, ""):
                problems.append("Invoice Unit missing - type it, or add Unit Size on the invoice")
            # batches
            alloc, short, deferred = [], 0.0, False
            need = float(it.get("qty") or 0)
            before = dict(left)
            part_batches = batches.get(it["part"], [])
            if chosen and need > 0 and not nosize:
                for b in part_batches:
                    if need <= 0:
                        break
                    avail = left.get(b["batch_no"], 0)
                    if avail <= 0:
                        continue
                    take = min(avail, need)
                    left[b["batch_no"]] = avail - take
                    need -= take
                    alloc.append(dict(batch_no=b["batch_no"], qty=take, balance=avail, created=b["created"]))
                short = round(need, 3)
                # The portal does not reduce batch balances for earlier invoices of the same file. If this
                # invoice only fits because an earlier invoice here used part of a batch, the portal reads it
                # as "Can't consume partially from previous batch" / "Consume batch in FIFO order".
                # Such invoices are held back for the next upload (after this one and a fresh DQMS report).
                ind, n2 = [], float(it.get("qty") or 0)
                for b in part_batches:
                    if n2 <= 0:
                        break
                    av = start.get(b["batch_no"], 0)
                    if av <= 0:
                        continue
                    t = min(av, n2)
                    n2 -= t
                    ind.append((b["batch_no"], t))
                if short <= 0 and [(a["batch_no"], a["qty"]) for a in alloc] != ind:
                    deferred = True
                    left.update(before)
            if nosize:
                problems, unit, unit_src = [], None, "none"
            elif chosen and need > 0 and not part_batches:
                problems.append(f"No batch for {it['part']} in the DQMS report")
            elif chosen and short > 0:
                problems.append(f"Batch balance short by {fmt(short)} (all batches of {it['part']} used up)")
            # what the portal said last time
            fails = [m for m in pmsgs if m["status"] and m["status"].upper() != "SUCCESS"
                     and (not m["part"] or m["part"] == it["part"] or m["record"] == "BATCH_DTLS")]
            if any("reason for gap" in (m["message"] or "").lower() for m in fails) and not reason:
                problems.append("Portal asked for a Reason for Gap - choose one")
            plant = plants.get(order, "")
            ln = dict(key=key, inv_no=inv["inv_no"], inv_date=inv["inv_date"], order_no=order, plant=plant,
                      part=it["part"], descr=it.get("descr", ""), qty=it.get("qty", 0), rate=it.get("rate"),
                      amount=it.get("amount"), dr=dr, drs=inv["drs"], line=line, line_src=line_src,
                      reason=reason, remarks=remarks, unit=unit, unit_src=unit_src, eway=eway, total=inv["total"],
                      cgst=inv["cgst"], sgst=inv["sgst"], igst=inv["igst"], batches=alloc, deferred=deferred, nosize=nosize,
                      batch_count=len(part_batches), short=short, problems=problems if chosen else [],
                      notes=notes, portal=pmsgs, run_id=inv["run_id"], selected=chosen,
                      file_name=inv["file_name"], edits=inv["edits"])
            lines.append(ln)
            if deferred:
                summary["deferred"] = summary.get("deferred", 0) + 1
            if nosize and chosen:
                summary["nosize"] = summary.get("nosize", 0) + 1
            if not chosen or deferred or nosize:
                continue
            summary["items"] += 1
            if problems:
                summary["blocked"] += 1
            r = [""] * len(COLS)
            r[COLS["flag"]] = "INVOICE_LR_DTLS"
            r[COLS["dr"]] = dr
            r[COLS["order"]] = order
            r[COLS["line"]] = "" if line is None else str(line)
            r[COLS["part"]] = it["part"]
            r[COLS["reason"]] = reason
            r[COLS["remarks"]] = remarks
            r[COLS["inv_no"]] = inv["inv_no"]
            r[COLS["inv_date"]] = dmy(inv["inv_date"])
            r[COLS["unit"]] = "" if unit in (None, "") else str(unit)
            r[COLS["value"]] = fmt(inv["total"])
            r[COLS["cgst"]] = fmt(inv["cgst"]) if inv["cgst"] else ""
            r[COLS["sgst"]] = fmt(inv["sgst"]) if inv["sgst"] else ""
            r[COLS["igst"]] = fmt(inv["igst"]) if inv["igst"] else ""
            r[COLS["eway"]] = eway
            r[COLS["transporter"]] = st["transporter"]
            r[COLS["batch_app"]] = st["batch_applicable"]
            out_rows.append(dict(cells=r, key=key, kind="inv"))
            if str(st["batch_applicable"]).upper() == "YES":
                for a in alloc:
                    b = [""] * len(COLS)
                    b[COLS["flag"]] = "BATCH_DTLS"
                    b[COLS["batch_no"]] = a["batch_no"]
                    b[COLS["batch_qty"]] = fmt(a["qty"])
                    b[COLS["batch_cons"]] = st["batch_considerable"]
                    out_rows.append(dict(cells=b, key=key, kind="batch"))
        if chosen and any(not l.get("deferred") and not l.get("nosize") for l in lines if l["inv_no"] == inv["inv_no"]):
            summary["invoices"] += 1
            summary["value"] += inv["total"] or 0
            if inv["run_id"]:
                summary["in_file"] += 1
    summary["rows"] = len(out_rows)
    summary["value"] = round(summary["value"], 2)

    rep = report_info()
    if not rep:
        warnings.append("No DQMS Batch Details report uploaded yet - drop the .xls downloaded from TAFE Channel.")
    else:
        last = rows("SELECT created_at FROM dqms_runs ORDER BY id DESC LIMIT 1")
        rep_time = rep.get("report_time") or rep.get("uploaded_at") or ""
        if last and rep_time and rep_time < last[0]["created_at"]:
            warnings.append(f"The DQMS report is from {rep_time[:16].replace('T', ' ')}, before the last file was made "
                            f"({last[0]['created_at'][:16].replace('T', ' ')}). If that file was uploaded on TAFE Channel, "
                            "download a fresh report so the batch balances include it.")
    if summary.get("nosize"):
        nl = sorted({ln["inv_no"] for ln in lines if ln.get("nosize") and ln["selected"]}, key=inv_sort_key)
        warnings.append(f"{len(nl)} invoice(s) left out - no Unit Size on the invoice: {', '.join(nl)}. "
                        "Add Unit Size in Tally and drop the invoice again, or type the Invoice Unit by hand.")
    if summary.get("deferred"):
        dl = sorted({ln["inv_no"] for ln in lines if ln.get("deferred")}, key=inv_sort_key)
        warnings.append(f"{len(dl)} invoice(s) held back for a 2nd upload: {', '.join(dl)}. The same part already uses "
                        "that batch earlier in this file, and the portal checks each invoice against the batch balance "
                        "from before the upload. Upload this file, download a fresh DQMS report, drop it here, then "
                        "download again for these.")
    if summary["in_file"]:
        warnings.append(f"{summary['in_file']} ticked invoice(s) were already put in an earlier file (History). "
                        "Only send them again if that upload failed.")
    return dict(lines=lines, rows=out_rows, warnings=warnings, summary=summary, report=rep, selected=sorted(sel),
                header=st["header"], settings=st)


def to_csv(header, out_rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(header)
    for r in out_rows:
        cells = list(r["cells"])
        cells += [""] * (len(header) - len(cells))
        w.writerow(cells[:len(header)])
    return buf.getvalue().encode("utf-8")
