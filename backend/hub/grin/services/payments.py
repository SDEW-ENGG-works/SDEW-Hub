"""TAFE payment data: the 'Payment Clearance Details' export and SDEW's invoice register.

Payment export (PaymentDetailsExport*.xls) - same reader as the Payment Marking app:
  title 'Payment Clearance Details for Vendor DS1615 from 01/10/2026 to 19/10/2026', header
  'Payment Voucher No. | GRIN Date | Cheque No. | Date | Amount (Rs.) | Ref Doc No. | Doc Type | Inv / Bill No. |
   Date | Debit (Rs.) | Credit (Rs.)'. Doc types RF/RG/RE/NM/NS = invoice paid (credit), ZK = debit note,
  KG = cash discount.
Invoice register ('New Microsoft Excel Worksheet 2026-2027.xlsx', the file Payment Marking marks):
  INVOICE NO | INVOICE DATE | AMOUNT | plant | payment details | payment date
  -> invoice value (with GST) and, when marked, the payment voucher + date.
"""
import re

from ...supp.services.readers import sheets
from .norm import inv_key, iso, num, voucher_key

TITLE = re.compile(r"payment clearance details for vendor\s+(\S+)(?:\s+from\s+(\S+)\s+to\s+(\S+))?", re.I)


# ----------------------------------------------------------------------------- payment export
def is_payment_export(path):
    for _, it in sheets(path):
        for i, row in enumerate(it):
            if i > 5:
                break
            for v in row:
                if isinstance(v, str) and TITLE.search(v):
                    return True
        break
    return False


def read_payments(path):
    vendor = period_from = period_to = ""
    head = None
    lines, vouchers = [], {}
    cur = None
    for _, it in sheets(path):
        for row in it:
            cells = [str(v).strip() if v is not None else "" for v in row]
            if head is None:
                for v in cells:
                    m = TITLE.search(v)
                    if m:
                        vendor, period_from, period_to = m.group(1), iso(m.group(2)), iso(m.group(3))
                low = [c.lower() for c in cells]
                if any(c.startswith("payment voucher") for c in low) and any("credit" in c for c in low):
                    head = _columns(low)
                continue
            g = lambda k: cells[head[k]] if head.get(k) is not None and head[k] < len(cells) else ""  # noqa: E731
            if g("pv"):
                cur = voucher_key(g("pv"))
                if cur not in vouchers:
                    vouchers[cur] = dict(pv=cur, pv_date=iso(g("pv_date")), amount=num(g("amount")))
            ref, inv = g("ref"), g("inv")
            if not cur or not ref or g("debit").lower() == "total":
                continue
            lines.append(dict(pv=cur, pv_date=vouchers[cur]["pv_date"], ref_doc=ref, doc_type=g("type").upper(),
                              inv_raw=inv, inv_key=inv_key(inv), inv_date=iso(g("inv_date")),
                              debit=round(num(g("debit")), 2), credit=round(num(g("credit")), 2)))
        break
    if head is None:
        raise ValueError("Payment export header not found")
    return dict(vendor=vendor, period_from=period_from, period_to=period_to,
                vouchers=list(vouchers.values()), lines=lines)


def _columns(low):
    idx = {}
    for i, c in enumerate(low):
        if c.startswith("payment voucher"):
            idx["pv"] = i
        elif c.startswith("amount"):
            idx["amount"] = i
        elif c.startswith("ref doc"):
            idx["ref"] = i
        elif c.startswith("doc type"):
            idx["type"] = i
        elif c.startswith("inv"):
            idx["inv"] = i
        elif c.startswith("debit"):
            idx["debit"] = i
        elif c.startswith("credit"):
            idx["credit"] = i
        elif c == "date":
            if "inv" in idx:
                idx["inv_date"] = i
            elif "pv_date" not in idx:
                idx["pv_date"] = i
    return idx


# ----------------------------------------------------------------------------- invoice register
REG_FIELDS = {
    "inv": ("invoice no", "invoice number", "inv no"),
    "date": ("invoice date", "inv date", "date"),
    "amount": ("amount", "invoice amount", "value"),
    "party": ("plant", "party", "customer", "party name"),
    "mark": ("payment details", "payment detail", "payment voucher", "payment no"),
    "mark_date": ("payment date", "paid date", "payment dt"),
}


def _reg_header(row):
    cells = [str(v).strip().lower() if v is not None else "" for v in row]
    cols = {}
    for f, names in REG_FIELDS.items():
        for n in names:
            if n in cells:
                cols[f] = cells.index(n)
                break
    return cols if "inv" in cols and "mark" in cols else None


def is_register(path):
    for _, it in sheets(path):
        for i, row in enumerate(it):
            if i > 15:
                break
            if _reg_header(row):
                return True
    return False


def read_register(path):
    """Every invoice row of the register's first sheet that has the header."""
    for name, it in sheets(path):
        cols, out = None, []
        for i, row in enumerate(it, start=1):
            if cols is None:
                if i > 15:
                    break
                cols = _reg_header(row)
                continue
            get = lambda f: row[cols[f]] if f in cols and cols[f] < len(row) else None  # noqa: E731
            inv = get("inv")
            if inv is None or str(inv).strip() == "":
                continue
            if isinstance(inv, float) and inv.is_integer():
                inv = int(inv)
            party = str(get("party") or "").strip()
            out.append(dict(inv_no=str(inv).strip(), inv_key=inv_key(inv), inv_date=iso(get("date")),
                            amount=round(num(get("amount")), 2), party=party,
                            pv=voucher_key(get("mark")), pv_date=iso(get("mark_date")),
                            cancelled=1 if "cancel" in party.lower() else 0))
        if cols:
            return dict(sheet=name, rows=out)
    raise ValueError("No 'INVOICE NO' + 'payment details' header found")
