"""Check a CHEP file against LEAP's 'Pending Inwards at C2' report.

The report lists every transfer SDEW posted that the TAFE plant has not accepted yet:
RECEIVER, INVOICE_NO, ITEMCODE, DISP_REC_QTY, DOCUMENT_NO, DOCUMENT_DATE ...
An invoice of our file is
  confirmed  - every SKU of it is in the report with the same quantity
  short      - in the report, but some SKU / quantity is less than in our file
  extra      - in the report with MORE than our file (posted twice?)
  missing    - not in the report: it failed in LEAP, or TAFE has already received it
LEAP sometimes drops the "/26-27" of an invoice (13347/26-27 -> 13347) when it splits one
invoice into two orders, so a report invoice without the suffix is matched on its number.
"""
import csv
import io
from collections import Counter, defaultdict


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _base(inv):
    return str(inv or "").strip().split("/")[0].strip()


def parse_pending_csv(data):
    """bytes/str of the report CSV -> list of dict rows."""
    if isinstance(data, bytes):
        data = data.decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(data)))
    if rows and "INVOICE_NO" not in rows[0]:
        raise ValueError("This is not the 'Pending Inwards at C2' report (no INVOICE_NO column)")
    return rows


def reconcile(run_rows, report_rows):
    """run_rows: the rows saved with a History file. Returns a summary + per-invoice list."""
    expected = defaultdict(Counter)          # (customer, invoice) -> {sku: qty}
    names = {}
    for r in run_rows:
        key = (str(r.get("customer") or "").strip(), str(r.get("invoice") or "").strip())
        expected[key][str(r.get("sku") or "").strip()] += _num(r.get("qty"))
        names.setdefault(key, r.get("remarks") or "")

    by_exact = defaultdict(Counter)
    by_base = defaultdict(Counter)            # report invoices WITHOUT a suffix, matched on number
    docs = defaultdict(set)
    for r in report_rows:
        cust = str(r.get("RECEIVER") or "").strip()
        inv = str(r.get("INVOICE_NO") or "").strip()
        sku = str(r.get("ITEMCODE") or "").strip()
        q = _num(r.get("DISP_REC_QTY"))
        if "/" in inv:
            by_exact[(cust, inv)][sku] += q
        else:
            by_base[(cust, inv)][sku] += q
        docs[(cust, _base(inv))].add(str(r.get("DOCUMENT_NO") or "").strip())

    out, totals = [], Counter()
    for (cust, inv), want in expected.items():
        got = Counter(by_exact.get((cust, inv), Counter()))
        got.update(by_base.get((cust, _base(inv)), Counter()))
        if not got:
            status = "missing"
        elif all(got[s] == q for s, q in want.items()) and set(got) <= set(want):
            status = "confirmed"
        elif any(got[s] > q for s, q in want.items()) or set(got) - set(want):
            status = "extra"
        else:
            status = "short"
        totals[status] += 1
        out.append(dict(customer=cust, invoice=inv, part=names.get((cust, inv), ""), status=status,
                        expected={k: v for k, v in want.items()}, found={k: v for k, v in got.items()},
                        documents=sorted(d for d in docs.get((cust, _base(inv)), set()) if d)))
    order = {"missing": 0, "short": 1, "extra": 2, "confirmed": 3}
    out.sort(key=lambda x: (order[x["status"]], x["invoice"]))
    return dict(invoices=len(out), confirmed=totals["confirmed"], missing=totals["missing"],
                short=totals["short"], extra=totals["extra"], lines=out)


def problem_rows(run_rows, result):
    """Template rows of the invoices that did not go through (for a retry file)."""
    bad = {(l["customer"], l["invoice"]) for l in result["lines"] if l["status"] == "missing"}
    return [r for r in run_rows
            if (str(r.get("customer") or "").strip(), str(r.get("invoice") or "").strip()) in bad]
