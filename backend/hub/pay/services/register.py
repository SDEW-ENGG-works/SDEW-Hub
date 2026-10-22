"""The invoice register (e.g. 'New Microsoft Excel Worksheet 2026-2027.xlsx').

Expected header (any order, any case):  INVOICE NO | INVOICE DATE | AMOUNT | plant | payment details | payment date
Payment details = TAFE payment voucher number, payment date = voucher date (dd.mm.yyyy).
"""
from ...grin.services.norm import inv_key, iso, num, voucher_key
from ...supp.services.readers import sheets

FIELDS = {
    "inv": ("invoice no", "invoice number", "inv no", "voucher no"),
    "date": ("invoice date", "inv date", "date"),
    "amount": ("amount", "invoice amount", "value"),
    "party": ("plant", "party", "customer", "party name"),
    "mark": ("payment details", "payment detail", "payment voucher", "payment no"),
    "mark_date": ("payment date", "paid date", "payment dt"),
}


def find_header(row):
    """Returns {field: column index} when this row is the register header, else None."""
    cells = [str(v).strip().lower() if v is not None else "" for v in row]
    cols = {}
    for f, names in FIELDS.items():
        for n in names:
            if n in cells:
                cols[f] = cells.index(n)
                break
    if "inv" in cols and "mark" in cols:
        return cols
    return None


def locate(path):
    """(sheet name, header row number (1-based), columns) of the register in a workbook, or None."""
    for name, it in sheets(path):
        for i, row in enumerate(it, start=1):
            if i > 15:
                break
            cols = find_header(row)
            if cols:
                return name, i, cols
    return None


def read_register(path):
    """All invoice rows: list of dicts with the Excel row number (to write the mark back)."""
    loc = locate(path)
    if not loc:
        raise ValueError("No 'INVOICE NO' + 'payment details' header found")
    sheet, hdr, cols = loc
    out = []
    for name, it in sheets(path):
        if name != sheet:
            continue
        for i, row in enumerate(it, start=1):
            if i <= hdr:
                continue
            get = lambda f: row[cols[f]] if f in cols and cols[f] < len(row) else None
            inv = get("inv")
            if inv is None or str(inv).strip() == "":
                continue
            party = str(get("party") or "").strip()
            out.append(dict(row=i, inv=str(inv).strip(), key=inv_key(inv), date=iso(get("date")),
                            amount=num(get("amount")), party=party,
                            mark=voucher_key(get("mark")), mark_date=iso(get("mark_date")) or str(get("mark_date") or ""),
                            cancelled="cancel" in party.lower()))
        break
    return dict(sheet=sheet, header_row=hdr, cols=cols, rows=out)
