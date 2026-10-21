"""Work out what a dropped file is from its contents, and which module it belongs to.

Rules mirror what the existing apps already recognise. Unknown files are kept in the
inbox as 'unknown' so nothing is lost.
"""
import io
import re

KINDS = {
    "po_htm":            ("PO (.htm)", "pos", "supp"),
    "tafe_po_export":    ("TAFE PO Details export", "pos", "supp"),
    "grin_xls":          ("TAFE GRIN Details", "grin", "supp"),
    "sales_register":    ("Tally Sales Register", "invoices", "supp"),
    "packing_list":      ("Packing list", "chep", "chep"),
    "leap_mis":          ("LEAP Customer MIS", "chep", "chep"),
    "chep_template":     ("CHEP BulkTransfer template", "chep", "chep"),
    "dqms_report":       ("DQMS Batch Details Report", "dqms", "dqms"),
    "dr_pdf":            ("Delivery Request PDF", "drs", "dqms"),
    "invoice_pdf":       ("Tally invoice PDF", "invoices", "dqms"),
    "dqms_status":       ("DQMS upload status", "dqms", "dqms"),
    "dqms_template":     ("DQMS template.csv", "dqms", "dqms"),
    "unknown":           ("Unknown file", "inbox", None),
}


def _text_of_sheet_file(name, data):
    """First few rows of an .xls/.xlsx as text, if the libraries are installed."""
    lower = name.lower()
    try:
        if lower.endswith(".xlsx"):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            parts = []
            for ws in wb.worksheets[:6]:
                parts.append(ws.title)
                for row in ws.iter_rows(max_row=15, values_only=True):
                    parts.extend(str(c) for c in row if c is not None)
            return " ".join(parts)
        if lower.endswith(".xls"):
            try:
                import xlrd
                wb = xlrd.open_workbook(file_contents=data)
                parts = []
                for sh in wb.sheets()[:6]:
                    parts.append(sh.name)
                    for r in range(min(15, sh.nrows)):
                        parts.extend(str(c) for c in sh.row_values(r) if c not in ("", None))
                return " ".join(parts)
            except Exception:
                # Many portal ".xls" exports are really HTML tables.
                return data[:200000].decode("utf-8", "ignore")
    except Exception:
        return ""
    return ""


def _pdf_text(data):
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(data))
        return " ".join((p.extract_text() or "") for p in reader.pages[:2])
    except Exception:
        return ""


def recognise(name, data):
    lower = name.lower()
    head = data[:300000].decode("utf-8", "ignore")

    if lower.endswith(".pdf"):
        if lower.startswith("deliveryrequest_"):
            return "dr_pdf"
        text = _pdf_text(data)
        if re.search(r"delivery\s*request", text, re.I):
            return "dr_pdf"
        if re.search(r"tax\s*invoice", text, re.I):
            return "invoice_pdf"
        return "unknown"

    if lower.endswith((".htm", ".html")):
        if re.search(r"purchase\s*order|FinalPriceChange", head, re.I):
            return "po_htm"
        return "unknown"

    if lower.endswith(".csv"):
        first = head.splitlines()[0] if head else ""
        if re.search(r"\b(TROUT|CUSTIN|LBINTOBIN)\b", head):
            return "leap_mis"
        if re.search(r"status|remarks|error", first, re.I) and "Invoice" in first:
            return "dqms_status"
        if "Batch Details Applicable" in first or "Invoice Unit" in first:
            return "dqms_template"
        return "unknown"

    if lower.endswith((".xls", ".xlsx")):
        text = _text_of_sheet_file(name, data)
        if lower.startswith("export") or "Price Effect From" in text:
            return "tafe_po_export"
        if re.search(r"GRIN", text) and re.search(r"Line", text, re.I):
            return "grin_xls"
        if re.search(r"Batch", text, re.I) and re.search(r"DQMS|Balance", text, re.I):
            return "dqms_report"
        if re.search(r"Sales Register|Voucher", text, re.I):
            return "sales_register"
        if "BulkTransfer" in name or re.search(r"Equipment Code|Sender", text):
            return "chep_template"
        if re.search(r"Invoice", text, re.I) and re.search(r"CHEP", text, re.I):
            return "packing_list"
        return "unknown"

    return "unknown"


def describe(kind):
    label, module, legacy = KINDS.get(kind, KINDS["unknown"])
    return {"kind": kind, "label": label, "module": module, "legacy": legacy}
