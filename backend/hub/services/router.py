"""One drop box for the whole hub: works out what each file is and hands it to the module that uses it.

  PDF                              -> DQMS   (Tally invoice PDFs, TAFE Delivery Request PDFs)
  .htm / .html TAFE PO             -> POs    (shared by Supplementary Bill and DQMS)
  .csv                             -> DQMS   (portal templateStatus.csv / blank template.csv)
  .xlsx CHEP BulkTransfer template -> CHEP   (replaces the template in use)
  .xls/.xlsx TAFE GRIN Details     -> Supplementary Bill
  .xls TAFE PO Details export      -> POs
  .xlsx Tally Sales Register       -> Supplementary Bill
  .xls DQMS Batch Details Report   -> DQMS
  .xls SDEW packing list           -> CHEP   (opens on the CHEP Create page)
  .xls TAFE Payment Clearance      -> Payments (also feeds GRIN & Payments)
  .xlsx SDEW invoice register      -> Payments (also feeds GRIN & Payments)
  .xlsx TAFE SALES DETAILS (GRN)   -> Payments, Sales marking
  .xml Tally export                -> GRIN & Payments
"""
import os
import tempfile

from ..http import ApiError

MODULE_NAMES = {"supp": "Supplementary Bill", "chep": "CHEP Transfer", "dqms": "DQMS Upload", "pos": "POs",
                "grin": "GRIN & Payments", "pay": "Payments"}


def _grin_kind(name, data):
    """'pay' for files of the Payments module: TAFE payment export, invoice register, TAFE SALES DETAILS."""
    from ..grin.services import payments
    from ..pay.services import sales
    fd, path = tempfile.mkstemp(suffix=os.path.splitext(name)[1] or ".xls")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        try:
            if payments.is_payment_export(path) or payments.is_register(path) or sales.locate(path):
                return True
            return False
        except Exception:  # noqa: BLE001
            return False
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _excel_kind(name, data):
    """'supp' / 'po' / 'dqms-report' / 'chep-template' / 'chep-packing' / None"""
    from ..chep.services import store as chep_store
    from ..dqms.services import dqms_report
    from ..supp.services.ingest import detect

    if data[:2] == b"PK" and chep_store.is_template(data):
        return "chep-template"
    fd, path = tempfile.mkstemp(suffix=os.path.splitext(name)[1] or ".xls")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        try:
            kind = detect(name, data, path)
        except Exception:  # noqa: BLE001 - not readable by the Supplementary Bill readers
            kind = None
        if kind in ("grin", "sales"):
            return "supp"
        if kind == "po-export":
            return "po"
        try:
            if dqms_report.looks_like_report(dqms_report.read_rows(name, data)):
                return "dqms-report"
        except Exception:  # noqa: BLE001
            pass
        try:
            from ..chep.services.defaults import load_settings
            from ..chep.services.packing import parse_packing_list
            if parse_packing_list(path, load_settings())["sheets"]:
                return "chep-packing"
        except Exception:  # noqa: BLE001
            pass
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def route_file(name, data):
    """-> dict(module, kind, page, result). Raises ApiError for files nobody uses."""
    from .. import db
    low = name.lower()
    if data[:5] == b"%PDF-" or low.endswith(".pdf"):
        from ..dqms.services import store
        res = store.ingest(name, data)
        mod, page = "dqms", "/dqms/"
    elif low.endswith(".xml") or b"<ENVELOPE" in data[:3000].upper():
        from ..grin.services.ingest import ingest
        res = ingest(name, data)
        mod, page = "grin", "/grin/#sources"
    elif low.endswith((".htm", ".html")) or data[:300].lstrip().lower().startswith((b"<html", b"<!doctype", b"<?xml")):
        from ..supp.services import po_parser
        if not po_parser.looks_like_po(data.decode("utf-8", errors="ignore")):
            raise ApiError(f"{name}: this web page is not a TAFE purchase order.")
        from ..supp.services.ingest import ingest
        res = ingest(name, data)
        mod, page = "pos", "/supp/#pos"
    elif low.endswith(".csv"):
        from ..dqms.services import store
        res = store.ingest(name, data)
        mod, page = "dqms", "/dqms/"
    elif low.endswith((".xls", ".xlsx", ".xlsm")) or data[:2] == b"PK" or data[:4] == b"\xd0\xcf\x11\xe0":
        kind = "grin" if _grin_kind(name, data) else _excel_kind(name, data)
        if kind == "grin":
            from ..pay.services.ingest import ingest
            res = ingest(name, data)
            mod, page = "pay", "/pay/#sales" if res.get("kind", "").startswith("Sales") else "/pay/"
        elif kind in ("supp", "po"):
            from ..supp.services.ingest import ingest
            res = ingest(name, data)
            mod, page = ("supp", "/supp/") if kind == "supp" else ("pos", "/supp/#pos")
        elif kind == "dqms-report":
            from ..dqms.services import store
            res = store.ingest(name, data)
            mod, page = "dqms", "/dqms/"
        elif kind in ("chep-template", "chep-packing"):
            from ..chep.services import store
            res = store.ingest(name, data)
            mod, page = "chep", "/chep/"
        else:
            raise ApiError(f"{name}: not recognised. Excel files the hub reads: TAFE GRIN Details, TAFE PO Details "
                           "export, Tally Sales Register, DQMS Batch Details Report, SDEW packing list, CHEP template.")
    else:
        raise ApiError(f"{name}: unknown file type. Drop PDF, .htm, .csv, .xls or .xlsx files.")
    msg = res.get("message") if isinstance(res, dict) else None
    if not msg and isinstance(res, dict):
        k = res.get("kind")
        if k == "invoices":
            msg = f"{len(res.get('new', []))} new / {len(res.get('updated', []))} updated invoice(s)"
        elif k == "drs":
            msg = f"Delivery Request {', '.join(res.get('drs', []))}: {res.get('lines')} line(s)"
        elif k == "report":
            msg = f"DQMS report: {res.get('batches')} batches for {res.get('parts')} parts"
        elif k == "status":
            msg = f"Portal status for {res.get('invoices')} invoice(s): {res.get('ok_rows')} ok, {res.get('failed_rows')} failed"
        elif k == "packing":
            msg = f"Packing list saved - open CHEP Transfer to make the template (sizes learned: {res.get('learned', 0)})"
        elif k == "template":
            msg = res.get("message") or "Template saved"
        elif k == "po":
            msg = f"PO {res.get('po_no')}: {res.get('items')} parts"
    db.log(mod, "upload", f"{name}: {msg or res.get('kind', '')}")
    return dict(module=mod, module_name=MODULE_NAMES[mod], page=page, file=name, message=msg or "Saved", result=res)
