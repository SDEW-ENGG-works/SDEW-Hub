"""The status of every TAFE invoice: GRINed? paid? - and who to remind.

Where each piece comes from (all already in the hub database):
  invoice      Tally (live pull, gp_tally_*)  >  Tally Sales Register upload (sales_lines)  >  invoice register
  GRIN         grin_lines  (Fetch GRIN from TAFE Channel, or a GRIN Details upload - shared with the Supp. Bill)
  payment      gp_pay_lines (TAFE Payment Clearance export)  +  the 'payment details' marks of the invoice register
Invoice numbers are compared after clean-up: 9552/26/27 = 9552/26-27 = 09552/26-27.

Status, in the order they need work:
  Not GRINed              no GRIN, invoice older than wait_days  -> reminder mail to the buyer
  GRIN short / rejected   GRIN qty below invoice qty, or TAFE rejected some qty
  Payment overdue         GRINed more than credit_days ago and not paid
  Awaiting payment        GRINed, not paid yet, still inside credit_days
  GRIN pending            no GRIN yet, but invoice younger than wait_days (normal)
  Debit note only         TAFE raised a debit note (ZK) but no payment line
  Paid                    payment voucher found
Ages are counted up to the date the data covers (last GRIN date / last payment date), never past it -
so an old GRIN download never makes a fresh invoice look 'Not GRINed'.
"""
import json
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

from ..db import rows
from .defaults import load_settings, plants
from .norm import inv_key

NOT_GRINED = "Not GRINed"
SHORT = "GRIN short / rejected"
OVERDUE = "Payment overdue"
AWAIT = "Awaiting payment"
WAIT = "GRIN pending"
DEBIT = "Debit note only"
PAID = "Paid"
ORDER = [NOT_GRINED, SHORT, OVERDUE, AWAIT, WAIT, DEBIT, PAID]

_cache = {"key": None, "at": 0, "data": None}


def invalidate():
    _cache.update(key=None, data=None)


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def buyers():
    return rows("SELECT * FROM gp_buyers ORDER BY plant, po_no, name")


def find_buyer(blist, plant, order_no):
    for b in blist:
        if b["po_no"] and order_no and b["po_no"].strip() == str(order_no).strip():
            return b
    for b in blist:
        if not (b["po_no"] or "").strip() and (b["plant"] or "").strip().upper() == (plant or "").upper():
            return b
    return None


def data_dates():
    g = (rows("SELECT MAX(grin_date) d, MIN(grin_date) f FROM grin_lines") or [{}])[0]
    p1 = (rows("SELECT MAX(period_to) d FROM gp_pay_files WHERE kind='Payments'") or [{}])[0].get("d") or ""
    p2 = (rows("SELECT MAX(pv_date) d FROM gp_pay_lines") or [{}])[0].get("d") or ""
    p3 = (rows("SELECT MAX(pv_date) d FROM gp_register WHERE pv<>''") or [{}])[0].get("d") or ""
    return dict(grin_until=g.get("d") or "", grin_from=g.get("f") or "", pay_until=max(p1, p2, p3))


def build(as_of=None):
    as_of = as_of or date.today().isoformat()
    key = as_of
    if _cache["key"] == key and time.time() - _cache["at"] < 120:
        return _cache["data"]
    data = _build(as_of)
    _cache.update(key=key, at=time.time(), data=data)
    return data


def _build(as_of):
    s = load_settings()
    today = _d(as_of) or date.today()
    pl = plants()
    by_party = {p["party"]: p for p in pl}
    tracked_party = {p["party"] for p in pl if p.get("grin_plant") or s["track_plants_without_grin"]}
    dates = data_dates()
    grin_until, pay_until = _d(dates["grin_until"]), _d(dates["pay_until"])

    inv = {}

    def rec(k, no, d, party):
        r = inv.get(k)
        if r is None:
            r = inv[k] = dict(inv_key=k, inv_no=no, inv_date=d or "", party=party or "", order_nos=[], lines={},
                              basic=0.0, gst_value=0.0, amount=None, amount_src="", sources=[], cancelled=0)
        return r

    # 1. Tally Sales Register upload (shared with the Supplementary Bill)
    for x in rows("SELECT voucher, part, inv_date, party, order_no, qty, rate, gst, item_name FROM sales_lines"):
        if x["party"] not in by_party:
            continue
        r = rec(inv_key(x["voucher"]), x["voucher"], x["inv_date"], x["party"])
        if "Sales Register" not in r["sources"]:
            r["sources"].append("Sales Register")
        q, rt = x["qty"] or 0, x["rate"] or 0
        r["lines"].setdefault(("SR", x["part"]), dict(part=x["part"], item=x["item_name"], qty=0.0, order_no=x["order_no"]))
        r["lines"][("SR", x["part"])]["qty"] += q
        r["basic"] += q * rt
        r["gst_value"] += q * rt * (x["gst"] or 0) / 100
        if x["order_no"] and x["order_no"] not in r["order_nos"]:
            r["order_nos"].append(x["order_no"])

    # 2. Tally live pull - the newest truth: replaces the lines read from the Sales Register
    tl = defaultdict(list)
    for x in rows("SELECT * FROM gp_tally_lines ORDER BY inv_key, seq"):
        tl[x["inv_key"]].append(x)
    for t in rows("SELECT * FROM gp_tally_invoices"):
        if t["party"] not in by_party:
            continue
        r = rec(t["inv_key"], t["inv_no"], t["inv_date"], t["party"])
        r.update(inv_no=t["inv_no"], inv_date=t["inv_date"] or r["inv_date"], party=t["party"])
        r["sources"].insert(0, f"Tally {t['company'] or ''}".strip())
        if t["cancelled"]:
            r["cancelled"] = 1
        if tl.get(t["inv_key"]):
            r["lines"] = {("T", i): dict(part=x["part"], item=x["item_name"], qty=x["qty"] or 0, order_no=x["order_no"])
                          for i, x in enumerate(tl[t["inv_key"]])}
            r["order_nos"] = []
            for x in tl[t["inv_key"]]:
                if x["order_no"] and x["order_no"] not in r["order_nos"]:
                    r["order_nos"].append(x["order_no"])
        if t["order_no"] and t["order_no"] not in r["order_nos"]:
            r["order_nos"].insert(0, t["order_no"])
        if t["amount"]:
            r["amount"], r["amount_src"] = t["amount"], "Tally"

    # 3. invoice register: value with GST, cancelled rows, payment marks
    reg_pay = {}
    for x in rows("SELECT * FROM gp_register"):
        if x["party"] not in by_party and x["inv_key"] not in inv:
            continue
        r = rec(x["inv_key"], x["inv_no"], x["inv_date"], x["party"] if x["party"] in by_party else "")
        if not r["party"] and x["party"] in by_party:
            r["party"] = x["party"]
        r["sources"].append("Register")
        if x["cancelled"]:
            r["cancelled"] = 1
        if r["amount"] is None and x["amount"]:
            r["amount"], r["amount_src"] = x["amount"], "Register"
        if x["pv"]:
            reg_pay[x["inv_key"]] = dict(pv=x["pv"], pv_date=x["pv_date"])

    # GRIN
    grin = {}
    for g in rows("SELECT invoice_no, grin_no, grin_date, plant, po_no, grin_qty, accepted_qty, rejected_qty FROM grin_lines"):
        k = inv_key(g["invoice_no"])
        a = grin.setdefault(k, dict(grin_nos=[], first=None, last=None, qty=0.0, acc=0.0, rej=0.0, plant=g["plant"], pos=[]))
        if g["grin_no"] not in a["grin_nos"]:
            a["grin_nos"].append(g["grin_no"])
        a["first"] = min(filter(None, [a["first"], g["grin_date"]])) if g["grin_date"] else a["first"]
        a["last"] = max(filter(None, [a["last"], g["grin_date"]])) if g["grin_date"] else a["last"]
        a["qty"] += g["grin_qty"] or 0
        a["acc"] += g["accepted_qty"] or 0
        a["rej"] += g["rejected_qty"] or 0
        if g["po_no"] and g["po_no"] not in a["pos"]:
            a["pos"].append(g["po_no"])

    # payments from the TAFE export
    ignore = {t.upper() for t in s["ignore_doc_types"]}
    pay = {}
    for p in rows("SELECT * FROM gp_pay_lines ORDER BY pv_date, pv"):
        if (p["doc_type"] or "").upper() in ignore or not p["inv_key"]:
            continue
        a = pay.setdefault(p["inv_key"], dict(credit=0.0, debit=0.0, pvs=[], pv="", pv_date="", types=[]))
        a["credit"] += p["credit"] or 0
        a["debit"] += p["debit"] or 0
        if p["doc_type"] not in a["types"]:
            a["types"].append(p["doc_type"])
        if (p["credit"] or 0) > 0:
            if p["pv"] not in a["pvs"]:
                a["pvs"].append(p["pv"])
            if (p["pv_date"] or "") >= a["pv_date"]:
                a["pv"], a["pv_date"] = p["pv"], p["pv_date"]

    # reminders already sent, notes / hold
    sent = defaultdict(list)
    for m in rows("SELECT mi.inv_key, m.sent_at FROM gp_mail_invoices mi JOIN gp_mails m ON m.id=mi.mail_id "
                  "WHERE m.status='Sent' ORDER BY m.sent_at"):
        sent[m["inv_key"]].append(m["sent_at"])
    notes = {n["inv_key"]: n for n in rows("SELECT * FROM gp_notes")}
    blist = buyers()

    out = []
    for k, r in inv.items():
        if r["cancelled"] or not r["party"] or r["party"] not in tracked_party:
            continue
        if not r["inv_date"] or r["inv_date"] < s["from_date"] or r["inv_date"] > as_of:
            continue
        p = by_party[r["party"]]
        idate = _d(r["inv_date"])
        inv_qty = round(sum(l["qty"] for l in r["lines"].values()), 3)
        g, py, rp = grin.get(k), pay.get(k), reg_pay.get(k)
        amount = r["amount"] if r["amount"] is not None else (round(r["basic"] + r["gst_value"], 2) if r["basic"] else None)
        order_no = (r["order_nos"] or [""])[0] or (g["pos"][0] if g and g["pos"] else "")
        msgs = []
        row = dict(inv_key=k, inv_no=r["inv_no"], inv_date=r["inv_date"], party=r["party"], plant=p["code"],
                   grin_plant=p.get("grin_plant", ""), order_no=order_no, amount=amount,
                   amount_src=r["amount_src"] or ("Sales Register" if r["basic"] else ""),
                   qty=inv_qty, parts=[dict(part=l["part"], item=l["item"], qty=l["qty"]) for l in r["lines"].values()],
                   sources=r["sources"], age=(today - idate).days if idate else None,
                   grin_nos=", ".join(g["grin_nos"]) if g else "", grin_date=(g["first"] if g else "") or "",
                   grin_qty=round(g["qty"], 3) if g else None, rejected=round(g["rej"], 3) if g else None,
                   pv="", pv_date="", credit=None, debit=None, paid_by="", due_date="", overdue_days=None)
        # payment
        if py and py["credit"] > 0:
            row.update(pv=py["pv"], pv_date=py["pv_date"], credit=round(py["credit"], 2), debit=round(py["debit"], 2),
                       paid_by="TAFE payment export")
            if len(py["pvs"]) > 1:
                msgs.append(f"Paid in {len(py['pvs'])} vouchers: {', '.join(py['pvs'])}")
            if py["debit"] > 0:
                msgs.append(f"Debit note Rs {py['debit']:,.2f} also against this invoice")
            if amount:
                ratio = py["credit"] / amount
                if not 0.985 <= ratio <= 1.002:
                    msgs.append(f"Paid Rs {py['credit']:,.2f} vs invoice Rs {amount:,.2f} ({(ratio - 1) * 100:+.2f}%)")
        elif rp:
            row.update(pv=rp["pv"], pv_date=rp["pv_date"], paid_by="Invoice register")
        paid = bool(row["pv"])

        if paid:
            status = PAID
            if not g:
                msgs.append("Paid - but this GRIN is not in the GRIN data")
        elif py and py["debit"] > 0:
            status = DEBIT
            row["debit"] = round(py["debit"], 2)
            msgs.append(f"Debit note Rs {py['debit']:,.2f} ({', '.join(py['types'])}) - no payment yet")
        elif g:
            short = inv_qty > 0 and g["qty"] < inv_qty - 0.001
            if short or g["rej"] > 0:
                status = SHORT
                if short:
                    msgs.append(f"GRIN qty {g['qty']:g} of invoice qty {inv_qty:g}")
                if g["rej"] > 0:
                    msgs.append(f"TAFE rejected {g['rej']:g}")
            else:
                status = AWAIT
            gd = _d(g["first"])
            if gd:
                due = gd + timedelta(days=s["credit_days"])
                row["due_date"] = due.isoformat()
                upto = min(today, pay_until) if pay_until else None
                if upto and upto > due and status == AWAIT:
                    status = OVERDUE
                    row["overdue_days"] = (upto - due).days
            if not pay_until:
                msgs.append("No payment data loaded yet")
        else:
            upto = min(today, grin_until) if grin_until else None
            if upto and idate and (upto - idate).days >= s["wait_days"]:
                status = NOT_GRINED
            else:
                status = WAIT
                if grin_until and idate and idate > grin_until:
                    msgs.append(f"GRIN data only up to {grin_until:%d-%b} - fetch GRIN")
        n = notes.get(k) or {}
        b = find_buyer(blist, p["code"], order_no)
        row.update(status=status, notes=msgs, note=n.get("note") or "", hold=bool(n.get("hold")),
                   reminders=len(sent.get(k, [])), last_reminder=(sent.get(k) or [""])[-1],
                   buyer_id=b["id"] if b else None, buyer=(b["name"] or b["email"]) if b else "")
        out.append(row)

    out.sort(key=lambda r: (ORDER.index(r["status"]), r["inv_date"], r["inv_no"]))
    counts = {st: dict(n=0, value=0.0) for st in ORDER}
    for r in out:
        counts[r["status"]]["n"] += 1
        counts[r["status"]]["value"] += r["amount"] or 0
    for c in counts.values():
        c["value"] = round(c["value"], 2)
    per_plant = defaultdict(lambda: defaultdict(int))
    for r in out:
        per_plant[r["plant"]][r["status"]] += 1
    return dict(as_of=as_of, rows=out, counts=counts, order=ORDER, dates=dates,
                plants=[dict(plant=k, **v) for k, v in sorted(per_plant.items())],
                settings=dict(wait_days=s["wait_days"], credit_days=s["credit_days"], from_date=s["from_date"]),
                untracked=[p["code"] for p in pl if p["party"] not in tracked_party],
                built_at=datetime.now().isoformat(timespec="seconds"))


def filtered(data, status="", plant="", q="", buyer=""):
    out = data["rows"]
    if status:
        out = [r for r in out if r["status"] == status]
    if plant:
        out = [r for r in out if r["plant"] == plant]
    if buyer:
        out = [r for r in out if str(r["buyer_id"] or "") == buyer or (buyer == "none" and not r["buyer_id"])]
    if q:
        ql = q.lower().strip()
        out = [r for r in out if ql in r["inv_no"].lower() or ql in (r["order_no"] or "").lower()
               or ql in r["grin_nos"].lower() or ql in (r["pv"] or "")
               or any(ql in (p["part"] or "").lower() for p in r["parts"])]
    return out


def to_json(v):
    return json.dumps(v, default=str)
