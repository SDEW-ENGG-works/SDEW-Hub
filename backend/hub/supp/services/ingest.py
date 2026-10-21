"""One upload box for everything: works out what each file is and saves it.

  .htm with 'Purchase order'            -> PO (prices by date, plant from Bill-to address)
  .xls/.xlsx starting 'GRIN No, ...'    -> TAFE GRIN details
  .xls/.xlsx with a Sales Register sheet -> Tally sales lines (+ SDEW GRN sheet if present)
"""
import json
import os
import re
from datetime import datetime

from .. import config
from ..db import get_db
from ..http import ApiError
from . import grin_parser, po_export_parser, po_parser, sales_parser
from .defaults import load_settings
from .readers import sheets


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _save_file(name, data):
    safe = re.sub(r"[^\w.\- ]", "_", os.path.basename(name or "upload"))
    stored = f"{datetime.now():%Y%m%d_%H%M%S_%f}_{safe}"
    with open(os.path.join(config.UPLOAD_DIR, stored), "wb") as fh:
        fh.write(data)
    return stored


def _record(kind, name, stored, nrows, info):
    con = get_db()
    cur = con.execute("INSERT INTO files(kind,name,stored,uploaded_at,rows,info) VALUES(?,?,?,?,?,?)",
                      (kind, name, stored, _now(), nrows, json.dumps(info)))
    return cur.lastrowid


def detect(name, data, path):
    head = data[:4096]
    if data[:2] == b"PK" or data[:4] == b"\xd0\xcf\x11\xe0":
        for _, it in sheets(path):
            first = next(it, None)
            if first and grin_parser.looks_like_grin(first):
                return "grin"
            if first and po_export_parser.looks_like_po_export(first):
                return "po-export"
            break
        if sales_parser.looks_like_sales(path):
            return "sales"
        return None
    try:
        html = data.decode("utf-8", errors="ignore")
    except Exception:
        return None
    if po_parser.looks_like_po(html):
        return "po"
    if b"<html" in head.lower() and b"GRIN No" in data[:20000]:
        return "grin-html"
    return None


def ingest(name, data, source="Upload"):
    stored = _save_file(name, data)
    path = os.path.join(config.UPLOAD_DIR, stored)
    kind = detect(name, data, path)
    if kind == "po":
        return _ingest_po(name, stored, data)
    if kind == "po-export":
        return _ingest_po_export(name, stored, path)
    if kind == "grin":
        return ingest_grin_file(path, name, stored, source)
    if kind == "sales":
        return _ingest_sales(name, stored, path)
    raise ApiError(f"{name}: not recognised. Upload a TAFE PO (.htm), a TAFE GRIN Details export (.xls) "
                   f"or the Tally Sales Register (.xlsx).")


def _ingest_po(name, stored, data):
    s = load_settings()
    words = [(p["code"], p.get("bill_to", "")) for p in s["plants"]]
    po = po_parser.parse(data.decode("utf-8", errors="ignore"), words)
    if not po["po_no"] or not po["items"]:
        raise ApiError(f"{name}: looks like a PO but no PO number / items could be read.")
    return _store_po(po, name, stored, "PO")


def _ingest_po_export(name, stored, path):
    s = load_settings()
    codes = {p["grin_plant"]: p["code"] for p in s["plants"] if p.get("grin_plant")}
    pos = po_export_parser.parse(path, codes)
    if not pos:
        raise ApiError(f"{name}: TAFE PO export has no lines.")
    results = [_store_po(po, name, stored, "PO export") for po in pos]
    r = results[0]
    if len(results) > 1:
        r = dict(r, message="; ".join(x["message"] for x in results))
    return r


def _store_po(po, name, stored, kind):
    con = get_db()
    old = con.execute("SELECT COUNT(*) FROM po_items WHERE po_no=?", (po["po_no"],)).fetchone()[0]
    keep, checks = {}, []
    if kind == "PO export" and old:
        # never let a 'new rate only' export overwrite date-wise prices from a full PO (.htm):
        # keep those parts, add only the parts the full PO does not have, and compare the new rates
        for r in con.execute("SELECT part, blocks FROM po_items WHERE po_no=?", (po["po_no"],)).fetchall():
            b = json.loads(r["blocks"])
            if not any(x.get("export") for x in b):
                keep[r["part"]] = b
        if keep:
            s = load_settings()
            from .po_parser import price_on
            for it in po["items"]:
                if it["part"] in keep:
                    n_old = price_on(keep[it["part"]], s["new_date"])
                    if n_old is not None and abs(n_old - it["rate"]) >= 0.005:
                        checks.append(f"{it['part']}: full PO {n_old} vs export {it['rate']}")
            po = dict(po, items=[it for it in po["items"] if it["part"] not in keep])
    if keep:
        con.execute("DELETE FROM po_items WHERE po_no=? AND part NOT IN (%s)" % ",".join("?" * len(keep)),
                    (po["po_no"], *keep.keys()))
    else:
        con.execute("DELETE FROM po_items WHERE po_no=?", (po["po_no"],))
    fid = _record("PO", name, stored, len(po["items"]),
                  dict(po_no=po["po_no"], plant=po["plant_hint"], kind=kind, warnings=(checks + po["warnings"])[:10]))
    if keep:   # header of the full PO stays; only count the added parts
        con.execute("UPDATE po_headers SET items=items+?, uploaded_at=? WHERE po_no=?",
                    (len(po["items"]), _now(), po["po_no"]))
    else:
        con.execute("INSERT INTO po_headers(po_no,plant,po_date,valid_till,bill_to,items,file_id,uploaded_at,source)"
                    " VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(po_no) DO UPDATE SET plant=excluded.plant,"
                    " po_date=excluded.po_date, valid_till=excluded.valid_till, bill_to=excluded.bill_to,"
                    " items=excluded.items, file_id=excluded.file_id, uploaded_at=excluded.uploaded_at,"
                    " source=excluded.source",
                    (po["po_no"], po["plant_hint"], po["po_date"], po["valid_till"], po["bill_to"], len(po["items"]), fid,
                     _now(), f"{kind}: {name}"))
    for it in po["items"]:
        con.execute("INSERT OR REPLACE INTO po_items(po_no,part,item,descr,uom,rate,blocks) VALUES(?,?,?,?,?,?,?)",
                    (po["po_no"], it["part"], it["item"], it["descr"], it["uom"], it["rate"], json.dumps(it["blocks"])))
    con.commit()
    if keep:
        msg = (f"PO {po['po_no']}: already loaded from the full PO - kept its {len(keep)} parts, added "
               f"{len(po['items'])} parts only in the export" + (f"; {len(checks)} rate(s) differ" if checks else "; new rates match"))
        return dict(kind="PO", file=name, po_no=po["po_no"], plant=po["plant_hint"] or "?", items=len(po["items"]),
                    revised=0, replaced=False, warnings=checks[:10], message=msg)
    revised = sum(1 for it in po["items"] if len(it["blocks"]) > 1)
    note = " (TAFE export: new rate only)" if kind == "PO export" else ""
    return dict(kind="PO", file=name, po_no=po["po_no"], plant=po["plant_hint"] or "?", items=len(po["items"]),
                revised=revised, replaced=bool(old), warnings=po["warnings"][:5],
                message=f"PO {po['po_no']} ({po['plant_hint'] or 'plant ?'}): {len(po['items'])} parts{note}"
                        + (" - replaced the earlier copy" if old else ""))


def ingest_grin_file(path, name, stored=None, source="Upload"):
    rows = grin_parser.parse(path)
    if not rows:
        raise ApiError(f"{name}: GRIN file has no lines.")
    con = get_db()
    now = _now()
    before = con.execute("SELECT COUNT(*) FROM grin_lines").fetchone()[0]
    for r in rows:
        con.execute("""INSERT INTO grin_lines VALUES(:grin_no,:line_no,:grin_date,:invoice_no,:invoice_date,:plant,:po_no,
            :po_date,:part_no,:part_desc,:grin_qty,:accepted_qty,:rejected_qty,:part_rate,:freight,:source,:file,:now)
            ON CONFLICT(grin_no,line_no) DO UPDATE SET grin_qty=excluded.grin_qty, accepted_qty=excluded.accepted_qty,
            rejected_qty=excluded.rejected_qty, invoice_no=excluded.invoice_no, part_no=excluded.part_no,
            po_no=excluded.po_no, part_rate=excluded.part_rate, freight=excluded.freight, source=excluded.source,
            source_file=excluded.source_file, updated_at=excluded.updated_at""",
                    dict(r, source=source, file=name, now=now))
    added = con.execute("SELECT COUNT(*) FROM grin_lines").fetchone()[0] - before
    dates = sorted(r["grin_date"] for r in rows if r["grin_date"])
    _record("GRIN", name, stored or os.path.basename(path), len(rows),
            dict(source=source, added=added, first=dates[0] if dates else "", last=dates[-1] if dates else ""))
    con.commit()
    return dict(kind="GRIN", file=name, lines=len(rows), added=added,
                message=f"GRIN {dates[0] if dates else ''} to {dates[-1] if dates else ''}: {len(rows)} lines ({added} new)")


def _ingest_sales(name, stored, path):
    sales, grn, used = sales_parser.parse(path)
    if not sales and not grn:
        raise ApiError(f"{name}: no Sales Register or GRN sheet found.")
    con = get_db()
    fid = _record("Sales", name, stored, len(sales), dict(sheets=used, grn_rows=len(grn)))
    for r in sales:
        con.execute("""INSERT OR REPLACE INTO sales_lines VALUES(:voucher,:part,:seq,:inv_date,:party,:order_no,:order_due,
            :item_name,:descr,:hsn,:gst,:qty,:rate,:fid)""", dict(r, fid=fid))
    for r in grn:
        con.execute("INSERT OR REPLACE INTO grn_sheet VALUES(:voucher,:part,:seq,:grn_no,:grn_date,:qty,:fid)",
                    dict(r, fid=fid))
    con.commit()
    dates = sorted(r["inv_date"] for r in sales if r["inv_date"])
    return dict(kind="Sales", file=name, lines=len(sales), grn_lines=len(grn), sheets=used,
                message=f"Sales Register {dates[0] if dates else ''} to {dates[-1] if dates else ''}: "
                        f"{len(sales)} lines" + (f", GRN sheet {len(grn)} lines" if grn else ""))
