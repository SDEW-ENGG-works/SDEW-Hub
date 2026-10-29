"""Upload: decide what a file is from its contents and load it."""
import json
import os
import re
import time
import zlib
from datetime import datetime

from ... import config
from ..db import get_db, one, rows, set_setting
from ...http import ApiError
from ...grin.services import payments
from . import register


def _store(name, data):
    safe = re.sub(r"[^\w.\- ()]+", "_", os.path.basename(name))[-120:] or "upload"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = os.path.join(config.upload_dir("pay"), f"{stamp}_{safe}")
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def _add_file(kind, name, path, n, info):
    """The file's bytes are kept in the database too: on Vercel the disk is wiped after every request."""
    with open(path, "rb") as fh:
        data = pack(fh.read())
    con = get_db()
    cur = con.execute("INSERT INTO pm_files(kind,name,stored,uploaded_at,rows,info,data) VALUES(?,?,?,?,?,?,?)",
                      (kind, name, os.path.basename(path), datetime.now().isoformat(timespec="seconds"), n,
                       json.dumps(info), data))
    fid = cur.lastrowid
    con.commit()
    return fid


MARK = b"ZL1:"


def pack(data):
    """zlib-compressed copy for the database (.xls shrinks ~5x; .xlsx is already zipped and stays as it is)."""
    z = zlib.compress(data, 6)
    return MARK + z if len(z) < len(data) * 0.9 else data


def unpack(data):
    data = bytes(data or b"")
    return zlib.decompress(data[len(MARK):]) if data.startswith(MARK) else data


def file_path(file_id):
    """Path of an uploaded file on this machine; written back from the database when it is not on disk."""
    f = one("SELECT stored FROM pm_files WHERE id=?", (file_id,))
    if not f:
        return None
    path = os.path.join(config.upload_dir("pay"), f["stored"])
    if not os.path.exists(path):
        d = one("SELECT data FROM pm_files WHERE id=?", (file_id,))
        if not d or not d["data"]:
            return None
        with open(path, "wb") as fh:
            fh.write(unpack(d["data"]))
    return path


def ingest(name, data):
    if not (data[:2] == b"PK" or data[:4] == b"\xd0\xcf\x11\xe0"):
        raise ApiError("Not an Excel file (.xls / .xlsx)")
    path = _store(name, data)
    t0 = time.time()
    res = _ingest(name, path)
    print(f"[pay] {name}: {res.get('kind')} read and saved in {time.time() - t0:.1f}s")
    return res


def _ingest(name, path):
    try:
        if payments.is_payment_export(path):
            r = _load_payments(name, path)
            _share_with_grin("store_payments", name, path)
            return r
        if register.locate(path):
            return save_register(name, path)
        from . import sales
        if sales.locate(path):
            return sales.save_sales_file(name, path)
    except ApiError:
        raise
    except Exception as e:  # unreadable workbook
        os.remove(path)
        raise ApiError(f"Could not read {name}: {e}")
    os.remove(path)
    raise ApiError("Not recognised: expected the invoice register (INVOICE NO … payment details), "
                   "a TAFE Payment Clearance Details export or the TAFE SALES DETAILS file (INVOICE NO … GRN NO).")


def _share_with_grin(fn, name, path):
    """The GRIN & Payments page reads the same payment export / register - keep it up to date too."""
    try:
        from ...grin.services import ingest as grin_ingest, status
        getattr(grin_ingest, fn)(name, os.path.basename(path), path)
        status.invalidate()
    except Exception as e:  # noqa: BLE001 - never let this stop the marking
        print(f"[pay] GRIN & Payments not updated: {e}")


def save_register(name, path, kind="Register"):
    reg = register.read_register(path)
    marked = sum(1 for r in reg["rows"] if r["mark"])
    info = dict(sheet=reg["sheet"], invoices=len(reg["rows"]), marked=marked,
                unmarked=sum(1 for r in reg["rows"] if not r["mark"] and not r["cancelled"]))
    fid = _add_file(kind, name, path, len(reg["rows"]), info)
    set_setting("register_file", fid)
    _share_with_grin("store_register", name, path)
    return dict(kind=kind, file_id=fid, message=f"{len(reg['rows']):,} invoices on sheet '{reg['sheet']}' · "
                f"{marked:,} already marked · {info['unmarked']:,} not marked", info=info)


def _load_payments(name, path):
    p = payments.read_payments(path)
    con = get_db()
    now = datetime.now().isoformat(timespec="seconds")
    info = dict(vendor=p["vendor"], period_from=p["period_from"], period_to=p["period_to"],
                vouchers=[v["pv"] for v in p["vouchers"]])
    fid = _add_file("Payments", name, path, len(p["lines"]), info)
    for v in p["vouchers"]:
        con.execute("INSERT INTO pm_vouchers(pv,pv_date,amount,vendor,file_id) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(pv) DO UPDATE SET pv_date=excluded.pv_date, amount=excluded.amount, "
                    "vendor=excluded.vendor, file_id=excluded.file_id",
                    (v["pv"], v["pv_date"], v["amount"], p["vendor"], fid))
    # only lines not in the database yet: loading the same export again sends nothing
    pvs = sorted({l["pv"] for l in p["lines"]})
    have = set()
    if pvs:
        have = {(r["pv"], r["ref_doc"], r["doc_type"], r["inv_raw"]) for r in rows(
            f"SELECT pv, ref_doc, doc_type, inv_raw FROM pm_pay_lines WHERE pv IN ({','.join('?' * len(pvs))})", pvs)}
    new, seen = [], set()
    for l in p["lines"]:
        k = (l["pv"], l["ref_doc"], l["doc_type"], l["inv_raw"])
        if k not in have and k not in seen:
            seen.add(k)
            new.append((l["pv"], l["pv_date"], l["ref_doc"], l["doc_type"], l["inv_raw"], l["inv_key"],
                        l["inv_date"], l["debit"], l["credit"], fid, now))
    from ...grin.services.ingest import _write_many
    _write_many(con, "INSERT OR IGNORE INTO pm_pay_lines(pv,pv_date,ref_doc,doc_type,inv_raw,inv_key,inv_date,"
                     "debit,credit,file_id,loaded_at)", new)
    con.commit()
    added = len(new)
    info["added"] = added
    con.execute("UPDATE pm_files SET info=? WHERE id=?", (json.dumps(info), fid))
    con.commit()
    per = f" {p['period_from']} to {p['period_to']}" if p["period_from"] else ""
    return dict(kind="Payments", file_id=fid, info=info,
                message=f"Vendor {p['vendor']}{per} · {len(p['vouchers'])} vouchers · {len(p['lines']):,} lines "
                        f"({added:,} new)")
