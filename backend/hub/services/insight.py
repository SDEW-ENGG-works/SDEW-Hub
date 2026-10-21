"""What only the hub can show: one picture across Supplementary Bill, CHEP and DQMS.

  overview()        Today page: the order-to-payment chain, money, checks that need a person
  search(q)         find an invoice / part / PO / DR / GRIN anywhere
  invoice_trail(n)  one invoice through Tally -> packing list -> CHEP -> DQMS -> GRIN -> supplementary bill
  part_view(p)      one part: PO lines and rates, CHEP size, DQMS batches, sales, GRIN, bill
  po_view(po)       one PO: parts and rates, sales, GRIN and bill lines on it
  dr_view(dr)       one Delivery Request: DR PDF lines, packing list lines, invoices
"""
import json
import re
from datetime import date, datetime, timedelta

from ..db import get_setting, one, rows

EWAY_LIMIT = 50000


def _n(sql, args=()):
    r = one(sql, args)
    return (r or {}).get("n") or 0


def _latest_bill():
    r = one("SELECT id, created_at, summary, params FROM bill_runs ORDER BY id DESC LIMIT 1")
    if not r:
        return None
    r["summary"] = json.loads(r["summary"] or "{}")
    r["params"] = json.loads(r["params"] or "{}")
    return r


def _like_json(field, value):
    return f'%"{field}": "{value}"%'


# --------------------------------------------------------------------------- Today
def _grin_data():
    try:
        from ..grin.services import status as gst
        return gst.build()
    except Exception:  # noqa: BLE001 - the Today page must open even if this module has a problem
        import traceback
        traceback.print_exc()
        return None


def _grin_counts():
    d = _grin_data()
    return d["counts"] if d else {}


def _grin_sub():
    c = _grin_counts()
    if not c:
        return "load payments on GRIN & Payments"
    ng, od = c.get("Not GRINed", {}).get("n", 0), c.get("Payment overdue", {}).get("n", 0)
    return f"{ng} not GRINed, {od} payment overdue"


def _grin_module():
    d = _grin_data()
    if not d:
        return dict(ok=False)
    c = d["counts"]
    return dict(ok=True, not_grined=c["Not GRINed"]["n"], not_grined_value=c["Not GRINed"]["value"],
                overdue=c["Payment overdue"]["n"], overdue_value=c["Payment overdue"]["value"],
                awaiting=c["Awaiting payment"]["n"] + c["GRIN short / rejected"]["n"],
                awaiting_value=c["Awaiting payment"]["value"] + c["GRIN short / rejected"]["value"],
                grin_until=d["dates"]["grin_until"], pay_until=d["dates"]["pay_until"])


def overview():
    today = date.today().isoformat()
    bill = _latest_bill()
    sales = one("SELECT COUNT(*) n, COUNT(DISTINCT voucher) inv, MIN(inv_date) first, MAX(inv_date) last FROM sales_lines") or {}
    grin = one("SELECT COUNT(*) n, COUNT(DISTINCT invoice_no) inv, MIN(grin_date) first, MAX(grin_date) last FROM grin_lines") or {}
    chep_last = one("SELECT id, created_at, file_name, doc_date, leap_status FROM chep_runs ORDER BY id DESC LIMIT 1")
    dqms_last = one("SELECT id, created_at, file_name, summary FROM dqms_runs ORDER BY id DESC LIMIT 1")
    if dqms_last:
        dqms_last["summary"] = json.loads(dqms_last["summary"] or "{}")
    report = get_setting("dqms.dqms_report") or {}

    # invoices sent to DQMS (History) - all of them, from every file made
    dqms_sent = set()
    for r in rows("SELECT invoices FROM dqms_runs"):
        dqms_sent.update(json.loads(r["invoices"] or "[]"))
    chep_invoices = set()
    for r in rows("SELECT rows FROM chep_runs"):
        for x in json.loads(r["rows"] or "[]"):
            if x.get("invoice"):
                chep_invoices.add(str(x["invoice"]).strip())

    chain = [
        dict(step="POs", count=_n("SELECT COUNT(*) n FROM po_headers"),
             sub=f"{_n('SELECT COUNT(*) n FROM po_items')} part lines", href="/supp/#pos"),
        dict(step="Delivery Requests", count=_n("SELECT COUNT(DISTINCT dr_no) n FROM delivery_requests"),
             sub="DR PDFs read", href="/dqms/"),
        dict(step="Invoices (Tally)", count=sales.get("inv") or 0,
             sub=f"{_dmy(sales.get('first'))} to {_dmy(sales.get('last'))}" if sales.get("n") else "upload the Sales Register",
             href="/supp/#uploads"),
        dict(step="CHEP transfers", count=len(chep_invoices),
             sub=f"invoices in {_n('SELECT COUNT(*) n FROM chep_runs')} History files", href="/chep/#history"),
        dict(step="DQMS uploads", count=len(dqms_sent),
             sub=f"invoices in {_n('SELECT COUNT(*) n FROM dqms_runs')} files", href="/dqms/#history"),
        dict(step="GRIN", count=grin.get("inv") or 0,
             sub=f"{_dmy(grin.get('first'))} to {_dmy(grin.get('last'))}" if grin.get("n") else "fetch or upload GRIN",
             href="/supp/#grin"),
        dict(step="Paid by TAFE", count=_grin_counts().get("Paid", {}).get("n", 0),
             sub=_grin_sub(), href="/grin/"),
        dict(step="Supplementary bill", count=(bill or {}).get("summary", {}).get("total", {}).get("bill_lines", 0),
             sub=f"lines, {_rs((bill or {}).get('summary', {}).get('total', {}).get('bill_value'))}" if bill else "not calculated yet",
             href="/supp/"),
    ]

    money = None
    if bill:
        t = bill["summary"].get("total", {})
        pend = {}
        for p in bill["summary"].get("plants", []):
            for cat, c in p.get("cats", {}).items():
                if cat != "Bill":
                    x = pend.setdefault(cat, dict(lines=0, value=0.0))
                    x["lines"] += c["lines"]
                    x["value"] = round(x["value"] + (c["value"] or 0), 2)
        money = dict(run_id=bill["id"], at=bill["created_at"], bill_value=t.get("bill_value"), gst=t.get("gst"),
                     with_gst=t.get("with_gst"), lines=t.get("bill_lines"),
                     plants=[dict(plant=p["plant"], value=p["bill_value"], lines=p["bill_lines"])
                             for p in bill["summary"].get("plants", []) if p.get("bill_lines")],
                     pending=pend)

    return dict(
        today=today, chain=chain, money=money, checks=checks(dqms_sent, chep_invoices, report),
        modules=dict(
            grin=_grin_module(),
            supp=dict(pos=_n("SELECT COUNT(*) n FROM po_headers"), grin_lines=grin.get("n") or 0,
                      grin_last=grin.get("last"), sales_lines=sales.get("n") or 0, sales_last=sales.get("last"),
                      bill_at=(bill or {}).get("created_at"), files=_n("SELECT COUNT(*) n FROM files")),
            chep=dict(packing_lists=_n("SELECT COUNT(*) n FROM batches"), files=_n("SELECT COUNT(*) n FROM chep_runs"),
                      last=chep_last, parts=_n("SELECT COUNT(*) n FROM part_types"),
                      leap_done=_n("SELECT COUNT(*) n FROM chep_runs WHERE leap_status IS NOT NULL AND leap_status<>''")),
            dqms=dict(invoices=_n("SELECT COUNT(*) n FROM invoices"),
                      waiting=_n("SELECT COUNT(*) n FROM invoices WHERE run_id IS NULL"),
                      files=_n("SELECT COUNT(*) n FROM dqms_runs"), last=dqms_last, report=report,
                      drs=_n("SELECT COUNT(DISTINCT dr_no) n FROM delivery_requests"),
                      typed=_n("SELECT COUNT(*) n FROM line_overrides")),
        ),
        open_items=rows("SELECT * FROM open_items WHERE status='open' ORDER BY module, id"),
        activity=rows("SELECT * FROM activity ORDER BY id DESC LIMIT 15"),
    )


def checks(dqms_sent=None, chep_invoices=None, report=None):
    """Every rule returns (module, title, how many, a few examples, where to fix it)."""
    out = []

    def add(module, title, items, href, detail=""):
        out.append(dict(module=module, title=title, count=len(items), items=items[:25], href=href, detail=detail))

    bill = _latest_bill()
    if bill:
        rid = bill["id"]
        g = rows("SELECT voucher ref, inv_date date, plant, part || '  ' || printf('%.2f', value) detail "
                 "FROM run_lines WHERE run_id=? AND cat='GRN pending' ORDER BY inv_date", (rid,))
        v = one("SELECT ROUND(SUM(value),2) v FROM run_lines WHERE run_id=? AND cat='GRN pending'", (rid,))["v"] or 0
        add("supp", "Supplementary bill lines waiting for TAFE's GRIN", g, "/supp/#review", f"{_rs(v)} can be claimed once GRIN is posted")
        rp = rows("SELECT voucher ref, inv_date date, plant, part || ' on PO ' || po_no detail FROM run_lines "
                  "WHERE run_id=? AND cat='Rate pending' ORDER BY inv_date", (rid,))
        add("supp", "Revised rate not received from TAFE", rp, "/supp/#review")
        ck = rows("SELECT DISTINCT part ref, plant, MIN(inv_date) date, "
                  "'Existing ' || printf('%.2f', old_rate) || ' -> Reversed ' || printf('%.2f', new_rate) detail "
                  "FROM run_lines WHERE run_id=? AND cat='Bill' AND notes LIKE '%CHECK Existing Rate%' GROUP BY part, plant",
                  (rid,))
        add("supp", "Existing Rate to confirm (jump over 6.5%)", ck, "/supp/")
        miss = [dict(ref=po, detail=f"{n} sales line(s) left out") for po, n in bill["summary"].get("missing_pos", [])[:25]]
        add("pos", "POs not uploaded yet (lines left out of the bill)", miss, "/supp/#review")

    # DQMS
    waiting = rows("SELECT inv_no ref, inv_date date, printf('%.2f', total) detail FROM invoices WHERE run_id IS NULL")
    add("dqms", "Invoices read but not yet in a DQMS file", waiting, "/dqms/")
    eway = []
    for r in rows("SELECT inv_no, inv_date, total, eway, edits FROM invoices WHERE total > ?", (EWAY_LIMIT,)):
        e = (json.loads(r["edits"] or "{}").get("eway") or r["eway"] or "").replace(" ", "")
        if not re.fullmatch(r"\d{12}", e):
            eway.append(dict(ref=r["inv_no"], date=r["inv_date"], detail=f"Value {_rs(r['total'])}"))
    add("dqms", "E-way Bill No. needed (value above Rs 50,000)", eway, "/dqms/")
    failed = rows("SELECT inv_no ref, MAX(uploaded_at) date, GROUP_CONCAT(DISTINCT message) detail FROM portal_status "
                  "WHERE UPPER(status)<>'SUCCESS' GROUP BY inv_no")
    add("dqms", "Rejected by the DQMS portal (last status file)", failed, "/dqms/")
    if report is None:
        report = get_setting("dqms.dqms_report") or {}
    rt = (report or {}).get("report_time") or (report or {}).get("uploaded_at") or ""
    if not rt or rt[:10] < (date.today() - timedelta(days=1)).isoformat():
        add("dqms", "DQMS Batch Details report is not from today",
            [dict(ref=(report or {}).get("name", "none uploaded"), date=rt[:10], detail="FIFO needs a fresh report")],
            "/dqms/")

    # CHEP
    not_sent = rows("SELECT file_name ref, doc_date date, created_at detail FROM chep_runs "
                    "WHERE (leap_status IS NULL OR leap_status='') ORDER BY id DESC")
    add("chep", "CHEP files not yet uploaded to LEAP from the hub", not_sent, "/chep/#history",
        "uploads done by hand on LEAP are not recorded here")
    leap_miss = []
    for r in rows("SELECT file_name, doc_date, leap_result FROM chep_runs WHERE leap_result IS NOT NULL AND leap_result<>''"):
        res = json.loads(r["leap_result"] or "{}")
        m = res.get("missing") or 0
        if m:
            leap_miss.append(dict(ref=r["file_name"], date=r["doc_date"], detail=f"{m} invoice(s) missing at LEAP"))
    add("chep", "LEAP shows invoices missing after upload", leap_miss, "/chep/#leap")
    unsized = rows("SELECT part ref, part_name detail FROM part_types WHERE type IS NULL OR type=''")
    add("chep", "Parts without a CHEP size", unsized, "/chep/#parts")

    # GRIN & Payments
    gd = _grin_data()
    if gd:
        ng = [dict(ref=r["inv_no"], date=r["inv_date"], plant=r["plant"],
                   detail=f"{r['age']} days, no GRIN" + (f" - {r['reminders']} reminder(s)" if r["reminders"] else ""))
              for r in gd["rows"] if r["status"] == "Not GRINed" and not r["hold"]]
        add("grin", "Invoices not GRINed by TAFE (reminder due)", ng, "/grin/#mails",
            f"GRIN data up to {_dmy(gd['dates']['grin_until'])}" if gd["dates"]["grin_until"] else "no GRIN loaded")
        od = [dict(ref=r["inv_no"], date=r["grin_date"], plant=r["plant"],
                   detail=f"GRINed, {r['overdue_days']} days past due, {_rs(r['amount'])}")
              for r in gd["rows"] if r["status"] == "Payment overdue"]
        add("grin", "GRINed but TAFE payment overdue", od, "/grin/",
            f"payments up to {_dmy(gd['dates']['pay_until'])}" if gd["dates"]["pay_until"] else "no payment export loaded")

    # across modules
    if dqms_sent is None:
        dqms_sent = set()
        for r in rows("SELECT invoices FROM dqms_runs"):
            dqms_sent.update(json.loads(r["invoices"] or "[]"))
    grin_inv = {r["invoice_no"] for r in rows("SELECT DISTINCT invoice_no FROM grin_lines")}
    last_grin = (one("SELECT MAX(grin_date) d FROM grin_lines") or {}).get("d") or ""
    no_grin = []
    # dates read once (one query each) - not one query per invoice: on the website every query is a trip to the database
    inv_dates = {r["voucher"]: r["d"] for r in rows("SELECT voucher, MIN(inv_date) d FROM sales_lines GROUP BY voucher")}
    inv_dates.update({r["inv_no"]: r["inv_date"] for r in rows("SELECT inv_no, inv_date FROM invoices") if r["inv_date"]})
    for inv in sorted(dqms_sent):
        if inv in grin_inv:
            continue
        d = inv_dates.get(inv) or ""
        if d and last_grin and d <= (datetime.fromisoformat(last_grin) - timedelta(days=3)).date().isoformat():
            no_grin.append(dict(ref=inv, date=d, detail="sent on DQMS, no GRIN in the GRIN data yet"))
    add("cross", "Sent on DQMS but no GRIN after 3 days", no_grin, "/supp/#grin",
        f"GRIN data up to {_dmy(last_grin)}" if last_grin else "no GRIN loaded")
    unknown_parts = rows("SELECT DISTINCT b.part ref, b.descr detail FROM dqms_batches b "
                         "WHERE b.balance > 0 AND NOT EXISTS (SELECT 1 FROM po_items i WHERE i.part=b.part) LIMIT 50")
    add("cross", "Parts with DQMS batches but in no uploaded PO", unknown_parts, "/supp/#pos")
    return out


# --------------------------------------------------------------------------- search
def search(q):
    q = (q or "").strip()
    if len(q) < 2:
        return dict(q=q, groups=[])
    like = f"%{q}%"
    up = f"%{q.upper()}%"
    groups = []

    inv = rows("SELECT voucher ref, MIN(inv_date) date, party detail, COUNT(*) n FROM sales_lines "
               "WHERE voucher LIKE ? GROUP BY voucher ORDER BY inv_date DESC LIMIT 20", (like,))
    seen = {r["ref"] for r in inv}
    for r in rows("SELECT inv_no ref, inv_date date, consignee detail FROM invoices WHERE inv_no LIKE ? LIMIT 20", (like,)):
        if r["ref"] not in seen:
            inv.append(r)
            seen.add(r["ref"])
    for r in rows("SELECT DISTINCT invoice_no ref, invoice_date date, 'GRIN ' || grin_no detail FROM grin_lines "
                  "WHERE invoice_no LIKE ? LIMIT 20", (like,)):
        if r["ref"] not in seen:
            inv.append(r)
            seen.add(r["ref"])
    groups.append(dict(kind="invoice", title="Invoices", items=inv[:25]))

    parts = rows("SELECT part ref, MAX(descr) detail, COUNT(DISTINCT po_no) n FROM po_items "
                 "WHERE UPPER(part) LIKE ? OR UPPER(descr) LIKE ? GROUP BY part LIMIT 25", (up, up))
    seenp = {r["ref"] for r in parts}
    for r in rows("SELECT part ref, part_name detail FROM part_types WHERE UPPER(part) LIKE ? OR UPPER(part_name) LIKE ? LIMIT 25",
                  (up, up)):
        if r["ref"] not in seenp:
            parts.append(r)
            seenp.add(r["ref"])
    groups.append(dict(kind="part", title="Parts", items=parts[:25]))

    groups.append(dict(kind="po", title="POs", items=rows(
        "SELECT po_no ref, plant detail, items n FROM po_headers WHERE po_no LIKE ? LIMIT 20", (like,))))
    drs = rows("SELECT dr_no ref, MAX(order_no) detail, COUNT(*) n FROM delivery_requests WHERE dr_no LIKE ? GROUP BY dr_no LIMIT 20",
               (like,))
    if re.fullmatch(r"\d{6,9}", q) and not drs:
        if one("SELECT 1 x FROM batches WHERE parsed LIKE ? LIMIT 1", (_like_json("dr", q),)):
            drs = [dict(ref=q, detail="on a packing list")]
    groups.append(dict(kind="dr", title="Delivery Requests", items=drs))
    groups.append(dict(kind="grin", title="GRIN", items=rows(
        "SELECT grin_no ref, grin_date date, invoice_no || '  ' || part_no detail FROM grin_lines WHERE grin_no LIKE ? "
        "ORDER BY grin_date DESC LIMIT 20", (like,))))
    return dict(q=q, groups=[g for g in groups if g["items"]])


# --------------------------------------------------------------------------- invoice trail
def invoice_trail(no):
    no = (no or "").strip()
    if not no:
        return None
    lead = re.match(r"\d+", no)
    out = dict(invoice=no, steps=[])

    sales = rows("SELECT voucher, part, seq, inv_date, party, order_no, item_name, descr, hsn, gst, qty, rate "
                 "FROM sales_lines WHERE voucher=? ORDER BY part, seq", (no,))
    out["steps"].append(dict(key="tally", title="Tally invoice (Sales Register)", ok=bool(sales), rows=sales,
                             note="" if sales else "not in the Sales Register uploaded so far"))

    pl = []
    for b in rows("SELECT id, name, uploaded_at, parsed FROM batches WHERE parsed LIKE ? ORDER BY id DESC",
                  (_like_json("invoice", no),)):
        parsed = json.loads(b["parsed"] or "{}")
        for s in parsed.get("sheets", []):
            for ln in s.get("lines", []):
                if str(ln.get("invoice", "")).strip() == no:
                    pl.append(dict(batch=b["id"], file=b["name"], sheet=s.get("name"), plant=s.get("plant"),
                                   dr=ln.get("dr"), part=ln.get("part"), part_name=ln.get("part_name"), qty=ln.get("qty"),
                                   chep=ln.get("chep"), carton=ln.get("carton"), sizes=ln.get("sizes")))
        if pl:
            break   # the newest packing list that has it
    out["steps"].append(dict(key="packing", title="Packing list (dispatch)", ok=bool(pl), rows=pl,
                             note="" if pl else "not on an uploaded packing list"))

    chep = []
    for r in rows("SELECT id, file_name, doc_date, created_at, leap_status, rows FROM chep_runs WHERE rows LIKE ? ORDER BY id",
                  (_like_json("invoice", no),)):
        for x in json.loads(r["rows"] or "[]"):
            if str(x.get("invoice", "")).strip() == no:
                chep.append(dict(run_id=r["id"], file=r["file_name"], doc_date=r["doc_date"], made=r["created_at"],
                                 leap=r["leap_status"] or "", sku=x.get("sku"), qty=x.get("qty"), plant=x.get("plant"),
                                 customer=x.get("customer")))
    carton_only = pl and all((x.get("chep") or 0) == 0 for x in pl)
    out["steps"].append(dict(key="chep", title="CHEP transfer (BulkTransfer file)", ok=bool(chep) or bool(carton_only),
                             rows=chep, note=("carton only - no CHEP needed" if carton_only and not chep else
                                              "" if chep else "not in any CHEP History file")))

    dq = one("SELECT inv_no, inv_date, order_no, total, cgst, sgst, igst, packages, drs, items, eway, edits, run_id, "
             "file_name FROM invoices WHERE inv_no=?", (no,))
    dq_runs = rows("SELECT id, created_at, file_name FROM dqms_runs WHERE invoices LIKE ? ORDER BY id", (f'%"{no}"%',))
    status = rows("SELECT seq, record, part, batch_no, status, message, file_name, uploaded_at FROM portal_status "
                  "WHERE inv_no=? ORDER BY seq", (no,))
    if dq:
        for k in ("drs", "items", "edits"):
            dq[k] = json.loads(dq[k] or ("{}" if k == "edits" else "[]"))
    out["steps"].append(dict(key="dqms", title="DQMS upload (TAFE Channel)", ok=bool(dq_runs), invoice=dq, rows=dq_runs,
                             status=status, note="" if dq_runs else ("read, not yet in a DQMS file" if dq else
                                                                     "not in any DQMS file made in the hub")))

    drs = set()
    for x in pl:
        if x.get("dr"):
            drs.add(str(x["dr"]))
    if dq:
        drs.update(str(d) for d in dq["drs"])
        if dq["edits"].get("dr"):
            drs.add(dq["edits"]["dr"])
    dr_rows = []
    for d in sorted(drs):
        dr_rows += rows("SELECT dr_no, part, order_no, descr, bin, req, size, qty FROM delivery_requests WHERE dr_no=?", (d,))
    out["steps"].insert(1, dict(key="dr", title="Delivery Request (DR)", ok=bool(drs), rows=dr_rows, drs=sorted(drs),
                                note="" if drs else "no DR number found"))

    grin = rows("SELECT grin_no, line_no, grin_date, invoice_no, plant, po_no, part_no, part_desc, grin_qty, accepted_qty, "
                "rejected_qty, part_rate, freight FROM grin_lines WHERE invoice_no=? ORDER BY grin_no, line_no", (no,))
    if not grin and lead:
        grin = rows("SELECT grin_no, line_no, grin_date, invoice_no, plant, po_no, part_no, part_desc, grin_qty, accepted_qty, "
                    "rejected_qty, part_rate, freight FROM grin_lines WHERE invoice_no LIKE ? ORDER BY grin_no, line_no",
                    (lead.group(0) + "%",))
        grin = [g for g in grin if re.match(r"\d+", g["invoice_no"] or "") and
                re.match(r"\d+", g["invoice_no"]).group(0) == lead.group(0)]
    out["steps"].append(dict(key="grin", title="GRIN (TAFE goods receipt)", ok=bool(grin), rows=grin,
                             note="" if grin else "no GRIN yet"))

    bill = _latest_bill()
    bl = rows("SELECT plant, cat, reason, part, qty, rate, old_rate, new_rate, diff, value, po_no, grn_no, status, notes "
              "FROM run_lines WHERE run_id=? AND voucher=? ORDER BY part", (bill["id"], no)) if bill else []
    settled = ("Already billed at Reversed Rate", "No price change")
    out["steps"].append(dict(key="bill", title="Supplementary bill (price revision)",
                             ok=bool(bl) and all(x["cat"] == "Bill" or x["reason"] in settled for x in bl),
                             rows=bl, run=bill and dict(id=bill["id"], at=bill["created_at"]),
                             note="" if bl else ("not a TAFE plant invoice in the last bill" if bill else "no bill calculated")))
    out["found"] = any(s["rows"] or s.get("invoice") for s in out["steps"])
    return out


# --------------------------------------------------------------------------- part / PO / DR
def part_view(part):
    from ..supp.services.defaults import load_settings
    from ..supp.services.po_parser import price_on
    part = (part or "").strip().upper()
    s = load_settings()
    items = rows("SELECT i.po_no, i.item, i.descr, i.uom, i.rate, i.blocks, h.plant FROM po_items i "
                 "LEFT JOIN po_headers h USING(po_no) WHERE i.part=? ORDER BY h.plant, i.po_no", (part,))
    for it in items:
        b = json.loads(it.pop("blocks") or "[]")
        it["old"], it["new"] = (price_on(b, s["old_date"]), price_on(b, s["new_date"])) if b else (None, None)
        it["blocks"] = len(b)
    size = one("SELECT type, part_name, source, updated_at FROM part_types WHERE part=?", (part,))
    batches = rows("SELECT batch_no, total, consumed, balance, created FROM dqms_batches WHERE part=? ORDER BY created", (part,))
    sales = rows("SELECT voucher, inv_date, party, order_no, qty, rate FROM sales_lines WHERE part=? "
                 "ORDER BY inv_date DESC LIMIT 30", (part,))
    sales_tot = one("SELECT COUNT(*) n, SUM(qty) q, MIN(inv_date) first, MAX(inv_date) last FROM sales_lines WHERE part=?", (part,))
    grin_tot = one("SELECT COUNT(*) n, SUM(grin_qty) q, SUM(rejected_qty) rej, MAX(grin_date) last FROM grin_lines WHERE part_no=?",
                   (part,))
    bill = _latest_bill()
    bill_tot = rows("SELECT plant, cat, COUNT(*) n, SUM(qty) q, ROUND(SUM(value),2) v FROM run_lines WHERE run_id=? AND part=? "
                    "GROUP BY plant, cat", (bill["id"], part)) if bill else []
    name = (items[0]["descr"] if items else "") or (size or {}).get("part_name") or (sales[0]["voucher"] and "") or ""
    return dict(part=part, name=name, po_items=items, chep_size=size, batches=batches,
                balance=round(sum(b["balance"] or 0 for b in batches), 3), sales=sales, sales_total=sales_tot,
                grin_total=grin_tot, bill=bill_tot, old_date=s["old_date"], new_date=s["new_date"])


def po_view(po_no):
    h = one("SELECT * FROM po_headers WHERE po_no=?", (po_no,))
    if not h:
        return None
    from ..supp.services.defaults import load_settings
    from ..supp.services.po_parser import price_on
    s = load_settings()
    items = rows("SELECT part, item, descr, uom, rate, blocks FROM po_items WHERE po_no=? ORDER BY item", (po_no,))
    for it in items:
        b = json.loads(it.pop("blocks") or "[]")
        it["old"], it["new"] = (price_on(b, s["old_date"]), price_on(b, s["new_date"])) if b else (None, None)
    typed = rows("SELECT part, item, updated_at FROM line_overrides WHERE po_no=?", (po_no,))
    sales = one("SELECT COUNT(*) n, COUNT(DISTINCT voucher) inv, MAX(inv_date) last FROM sales_lines WHERE order_no=?", (po_no,))
    grin = one("SELECT COUNT(*) n, MAX(grin_date) last FROM grin_lines WHERE po_no=?", (po_no,))
    bill = _latest_bill()
    bl = rows("SELECT cat, COUNT(*) n, ROUND(SUM(value),2) v FROM run_lines WHERE run_id=? AND po_no=? GROUP BY cat",
              (bill["id"], po_no)) if bill else []
    return dict(header=h, items=items, typed=typed, sales=sales, grin=grin, bill=bl,
                old_date=s["old_date"], new_date=s["new_date"])


def dr_view(dr):
    dr = (dr or "").strip()
    lines = rows("SELECT dr_no, part, order_no, descr, bin, req, size, qty, file_name, uploaded_at FROM delivery_requests "
                 "WHERE dr_no=?", (dr,))
    pl = []
    for b in rows("SELECT id, name, parsed FROM batches WHERE parsed LIKE ? ORDER BY id DESC", (_like_json("dr", dr),)):
        for s in json.loads(b["parsed"] or "{}").get("sheets", []):
            for ln in s.get("lines", []):
                if str(ln.get("dr", "")).strip() == dr:
                    pl.append(dict(file=b["name"], sheet=s.get("name"), invoice=ln.get("invoice"), part=ln.get("part"),
                                   qty=ln.get("qty"), chep=ln.get("chep"), inv_date=ln.get("inv_date")))
        if pl:
            break
    invs = rows("SELECT inv_no, inv_date, total, run_id FROM invoices WHERE drs LIKE ? OR edits LIKE ?",
                (f'%"{dr}"%', f'%"{dr}"%'))
    return dict(dr=dr, lines=lines, packing=pl, invoices=invs)


# --------------------------------------------------------------------------- helpers
def _dmy(iso):
    return f"{iso[8:10]}-{iso[5:7]}-{iso[0:4]}" if iso and len(iso) >= 10 else ""


def _rs(v):
    if v in (None, ""):
        return "Rs 0"
    v = float(v)
    s = f"{abs(v):.2f}"
    whole, dec = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        whole = head + "," + tail
    return ("-" if v < 0 else "") + "Rs " + whole + "." + dec
