"""Monthly payment report: how much TAFE paid us in a month, and where the rest stands.

For a month (yyyy-mm) it answers:
  Received   every payment voucher (PV) dated in the month: invoices paid (gross), debit notes (ZK),
             cash discount (KG), other deductions and the net that reached the bank - per voucher,
             per plant and per invoice. Days from invoice and from GRIN to payment; paid on time or late.
  Billed     the invoices raised in the month: how much is paid, GRINed and waiting, not GRINed.
  Pending    at the end of the month: every invoice raised up to then and not paid by then - overdue,
             not yet due, not GRINed.
  Trend      the same headline numbers for every month, side by side.

Where the payment comes from:
  TAFE Channel payment export (gp_pay_lines) - full detail with deductions. This is used first.
  Invoice register (gp_register pv / pv_date) - only for invoices the TAFE export does not have
  (months not fetched yet). The register has no deductions, so net = invoice value there.
"""
from collections import defaultdict
from datetime import date, timedelta

from ..db import rows
from . import status as st
from .defaults import plants

_cache = dict(src=None, data=None)

DEBIT_NOTE, CASH_DISCOUNT = "ZK", "KG"


def _d(s):
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def _month_bounds(m):
    y, mo = int(m[:4]), int(m[5:7])
    start = date(y, mo, 1)
    end = (date(y + (mo == 12), mo % 12 + 1, 1)) - timedelta(days=1)
    return start, end


def _r(v):
    return round(v or 0.0, 2)


def invalidate():
    _cache.update(src=None, data=None)


def _base():
    """Every payment event (TAFE first, register for the rest) + the status rows. Cached 2 minutes."""
    data = st.build()                     # cached 2 minutes there; rebuilt here only when that changes
    if _cache["data"] and _cache["src"] is data:
        return _cache["data"]
    credit_days = data["settings"]["credit_days"]
    by_key = {r["inv_key"]: r for r in data["rows"]}

    # plant for invoices that are not on the status page (older / other parties)
    party_plant = {p["party"]: p["code"] for p in plants()}
    tally = {t["inv_key"]: t for t in rows("SELECT inv_key, inv_no, inv_date, party, amount FROM gp_tally_invoices")}
    reg = {x["inv_key"]: x for x in rows("SELECT inv_key, inv_no, inv_date, amount, party, pv, pv_date, cancelled "
                                         "FROM gp_register")}

    def info(k, fallback_no="", fallback_date=""):
        r = by_key.get(k)
        if r:
            return dict(inv_no=r["inv_no"], inv_date=r["inv_date"], plant=r["plant"], amount=r["amount"],
                        grin_date=r["grin_date"], due_date=r["due_date"])
        t, x = tally.get(k), reg.get(k)
        party = (t or {}).get("party") or (x or {}).get("party") or ""
        return dict(inv_no=(t or x or {}).get("inv_no") or fallback_no,
                    inv_date=(t or x or {}).get("inv_date") or fallback_date,
                    plant=party_plant.get(party) or (party[:18] if party else "Other"),
                    amount=(t or {}).get("amount") or (x or {}).get("amount"), grin_date="", due_date="")

    # ---- TAFE payment lines -> one event per (voucher, invoice)
    lines = rows("SELECT * FROM gp_pay_lines ORDER BY pv_date, pv")
    tafe_paid = set()
    events = []          # one per invoice per voucher
    deductions = []      # every debit line
    pvs = {}
    for p in lines:
        pv = pvs.setdefault(p["pv"], dict(pv=p["pv"], pv_date=p["pv_date"], source="TAFE Channel", invoices=set(),
                                          gross=0.0, debit_note=0.0, discount=0.0, other=0.0))
        cr, dr = p["credit"] or 0.0, p["debit"] or 0.0
        t = (p["doc_type"] or "").upper()
        if cr:
            pv["gross"] += cr
            if p["inv_key"]:
                pv["invoices"].add(p["inv_key"])
                tafe_paid.add(p["inv_key"])
            events.append(dict(inv_key=p["inv_key"], pv=p["pv"], pv_date=p["pv_date"], paid=cr, doc_type=t,
                               ref=p["inv_raw"], source="TAFE Channel"))
        if dr:
            kind = "Debit note" if t == DEBIT_NOTE else "Cash discount" if t == CASH_DISCOUNT else "Other deduction"
            pv["debit_note" if t == DEBIT_NOTE else "discount" if t == CASH_DISCOUNT else "other"] += dr
            deductions.append(dict(pv=p["pv"], pv_date=p["pv_date"], kind=kind, doc_type=t, ref=p["inv_raw"],
                                   ref_doc=p["ref_doc"], inv_key=p["inv_key"] if t != CASH_DISCOUNT else "",
                                   amount=dr))

    # ---- invoice register, only for invoices TAFE's export does not show as paid
    for k, x in reg.items():
        if not x["pv"] or not x["pv_date"] or x["cancelled"] or k in tafe_paid:
            continue
        r = by_key.get(k)
        amt = (r or {}).get("amount") or x["amount"] or 0.0
        pv = pvs.setdefault(x["pv"], dict(pv=x["pv"], pv_date=x["pv_date"], source="Invoice register",
                                          invoices=set(), gross=0.0, debit_note=0.0, discount=0.0, other=0.0))
        if pv["source"] == "TAFE Channel":
            pv["source"] = "TAFE + register"
        pv["gross"] += amt
        pv["invoices"].add(k)
        events.append(dict(inv_key=k, pv=x["pv"], pv_date=x["pv_date"], paid=amt, doc_type="",
                           ref=x["inv_no"], source="Invoice register"))

    # invoice details + days for every event
    for e in events:
        i = info(e["inv_key"], e["ref"])
        e.update(i)
        pd_, idt, gd, due = _d(e["pv_date"]), _d(i["inv_date"]), _d(i["grin_date"]), _d(i["due_date"])
        if not due and gd:
            due = gd + timedelta(days=credit_days)
        e["days_inv"] = (pd_ - idt).days if pd_ and idt else None
        e["days_grin"] = (pd_ - gd).days if pd_ and gd else None
        e["late_days"] = (pd_ - due).days if pd_ and due and pd_ > due else 0
        e["on_time"] = None if not (pd_ and due) else pd_ <= due
    for dd in deductions:
        dd["plant"] = info(dd["inv_key"])["plant"] if dd["inv_key"] else ""
        if dd["plant"] == "Other":
            dd["plant"] = "Not matched to an invoice"

    # when each invoice was (first) paid - for billed / pending
    first_paid = {}
    for e in events:
        k = e["inv_key"]
        if k and (k not in first_paid or e["pv_date"] < first_paid[k]):
            first_paid[k] = e["pv_date"]

    tafe_dates = [p["pv_date"] for p in lines if p["pv_date"]]
    res = dict(rows=data["rows"], events=events, deductions=deductions, pvs=pvs, first_paid=first_paid,
               credit_days=credit_days, wait_days=data["settings"]["wait_days"], dates=data["dates"],
               tafe_from=min(tafe_dates) if tafe_dates else "", tafe_to=max(tafe_dates) if tafe_dates else "")
    _cache.update(src=data, data=res)
    return res


def months():
    b = _base()
    ms = {e["pv_date"][:7] for e in b["events"] if e["pv_date"]}
    ms |= {r["inv_date"][:7] for r in b["rows"] if r["inv_date"]}
    return sorted(ms, reverse=True)


def _pending_at(b, end):
    """Invoices raised up to `end` and not paid by `end`."""
    e_iso = end.isoformat()
    out = dict(n=0, value=0.0, overdue_n=0, overdue_value=0.0, due_n=0, due_value=0.0, ng_n=0, ng_value=0.0, list=[])
    for r in b["rows"]:
        if not r["inv_date"] or r["inv_date"] > e_iso:
            continue
        paid_on = b["first_paid"].get(r["inv_key"])
        if paid_on and paid_on <= e_iso:
            continue
        amt = r["amount"] or 0.0
        out["n"] += 1
        out["value"] += amt
        gd = _d(r["grin_date"])
        if gd and gd <= end:
            due = gd + timedelta(days=b["credit_days"])
            if due < end:
                kind, out["overdue_n"], out["overdue_value"] = "Overdue", out["overdue_n"] + 1, out["overdue_value"] + amt
            else:
                kind, out["due_n"], out["due_value"] = "Not yet due", out["due_n"] + 1, out["due_value"] + amt
            late = (end - due).days if due < end else 0
        else:
            kind, out["ng_n"], out["ng_value"] = "Not GRINed", out["ng_n"] + 1, out["ng_value"] + amt
            due, late = None, 0
        out["list"].append(dict(inv_no=r["inv_no"], inv_date=r["inv_date"], plant=r["plant"], amount=amt,
                                grin_date=r["grin_date"] if gd and gd <= end else "",
                                due_date=due.isoformat() if due else "", kind=kind, late_days=late,
                                paid_on=paid_on or ""))
    for k in ("value", "overdue_value", "due_value", "ng_value"):
        out[k] = _r(out[k])
    order = {"Overdue": 0, "Not yet due": 1, "Not GRINed": 2}
    out["list"].sort(key=lambda x: (order[x["kind"]], -x["late_days"], x["inv_date"]))
    return out


def _headline(b, m):
    start, end = _month_bounds(m)
    s_iso, e_iso = start.isoformat(), end.isoformat()
    ev = [e for e in b["events"] if s_iso <= (e["pv_date"] or "") <= e_iso]
    pv = [p for p in b["pvs"].values() if s_iso <= (p["pv_date"] or "") <= e_iso]
    gross = sum(p["gross"] for p in pv)
    dn = sum(p["debit_note"] for p in pv)
    disc = sum(p["discount"] for p in pv)
    oth = sum(p["other"] for p in pv)
    billed = [r for r in b["rows"] if (r["inv_date"] or "")[:7] == m]
    src = {p["source"] for p in pv}
    return dict(month=m, payments=len(pv), invoices=len({e["inv_key"] for e in ev}), gross=_r(gross),
                debit_note=_r(dn), discount=_r(disc), other=_r(oth), net=_r(gross - dn - disc - oth),
                billed_n=len(billed), billed=_r(sum(r["amount"] or 0 for r in billed)),
                source="TAFE Channel" if src == {"TAFE Channel"} else "Invoice register" if src == {"Invoice register"}
                else ("TAFE Channel + register" if src else ""), ev=ev, pv=pv, billed_rows=billed, start=start, end=end)


def report(m=None):
    b = _base()
    ms = months()
    if not m:
        m = ms[0] if ms else date.today().strftime("%Y-%m")
    if len(m) != 7 or m[4] != "-":
        raise ValueError("month must be yyyy-mm")
    h = _headline(b, m)
    ev, start, end = h["ev"], h["start"], h["end"]

    # days to pay / on time
    di = [e["days_inv"] for e in ev if e["days_inv"] is not None]
    dg = [e["days_grin"] for e in ev if e["days_grin"] is not None]
    on = [e for e in ev if e["on_time"] is True]
    late = [e for e in ev if e["on_time"] is False]
    speed = dict(avg_inv=round(sum(di) / len(di), 1) if di else None,
                 avg_grin=round(sum(dg) / len(dg), 1) if dg else None,
                 on_time_n=len(on), on_time_value=_r(sum(e["paid"] for e in on)),
                 late_n=len(late), late_value=_r(sum(e["paid"] for e in late)),
                 late_avg=round(sum(e["late_days"] for e in late) / len(late), 1) if late else None,
                 unknown_n=len(ev) - len(on) - len(late))

    # per plant
    pl = defaultdict(lambda: dict(invoices=set(), gross=0.0, deductions=0.0, payments=set()))
    for e in ev:
        a = pl[e["plant"] or "Other"]
        a["invoices"].add(e["inv_key"])
        a["gross"] += e["paid"]
        a["payments"].add(e["pv"])
    for dd in b["deductions"]:
        if start.isoformat() <= dd["pv_date"] <= end.isoformat() and dd["plant"]:
            pl[dd["plant"]]["deductions"] += dd["amount"]
    by_plant = sorted([dict(plant=k, invoices=len(v["invoices"]), payments=len(v["payments"]), gross=_r(v["gross"]),
                            deductions=_r(v["deductions"]), net=_r(v["gross"] - v["deductions"]))
                       for k, v in pl.items()], key=lambda x: -x["gross"])
    # cash discount is per voucher, not per invoice: shown as its own line under the plants
    unassigned = _r(h["gross"] - h["debit_note"] - h["discount"] - h["other"] - sum(x["net"] for x in by_plant))

    # per voucher
    pvs = sorted([dict(pv=p["pv"], pv_date=p["pv_date"], source=p["source"], invoices=len(p["invoices"]),
                       gross=_r(p["gross"]), debit_note=_r(p["debit_note"]), discount=_r(p["discount"]),
                       other=_r(p["other"]), net=_r(p["gross"] - p["debit_note"] - p["discount"] - p["other"]))
                  for p in h["pv"]], key=lambda x: (x["pv_date"], x["pv"]))

    # by week of the month (when the money came)
    weeks = defaultdict(lambda: dict(gross=0.0, net=0.0, payments=0))
    for p in pvs:
        d = _d(p["pv_date"])
        wk = min((d.day - 1) // 7 + 1, 5)
        weeks[wk]["gross"] += p["gross"]
        weeks[wk]["net"] += p["net"]
        weeks[wk]["payments"] += 1
    by_week = [dict(week=k, label=f"{(k - 1) * 7 + 1}-{end.day if k == 5 else k * 7} {start:%b}",
                    gross=_r(v["gross"]), net=_r(v["net"]), payments=v["payments"]) for k, v in sorted(weeks.items())]

    # billed in the month: where those invoices stand now
    bs = defaultdict(lambda: dict(n=0, value=0.0))
    paid_in_month = 0.0
    for r in h["billed_rows"]:
        bs[r["status"]]["n"] += 1
        bs[r["status"]]["value"] += r["amount"] or 0
        fp = b["first_paid"].get(r["inv_key"])
        if fp and fp <= end.isoformat():
            paid_in_month += r["amount"] or 0
    billed = dict(n=h["billed_n"], value=h["billed"], paid_same_month=_r(paid_in_month),
                  by_status=[dict(status=s_, n=bs[s_]["n"], value=_r(bs[s_]["value"])) for s_ in st.ORDER if bs[s_]["n"]])

    pend = _pending_at(b, min(end, date.today()))
    pend_list = pend.pop("list")

    invoices = sorted([dict(inv_no=e["inv_no"], inv_date=e["inv_date"], plant=e["plant"], amount=e["amount"],
                            paid=_r(e["paid"]), pv=e["pv"], pv_date=e["pv_date"], grin_date=e["grin_date"],
                            days_inv=e["days_inv"], days_grin=e["days_grin"], late_days=e["late_days"],
                            on_time=e["on_time"], source=e["source"], doc_type=e["doc_type"])
                       for e in ev], key=lambda x: (x["pv_date"], x["pv"], x["inv_date"] or "", x["inv_no"] or ""))
    deds = sorted([dict(d_) for d_ in b["deductions"] if start.isoformat() <= d_["pv_date"] <= end.isoformat()],
                  key=lambda x: (x["pv_date"], x["kind"]))

    # last month for comparison + every month
    trend = []
    for mm in sorted(ms):
        hh = _headline(b, mm)
        p_ = _pending_at(b, min(hh["end"], date.today()))
        trend.append(dict(month=mm, payments=hh["payments"], invoices=hh["invoices"], gross=hh["gross"],
                          deductions=_r(hh["debit_note"] + hh["discount"] + hh["other"]), net=hh["net"],
                          billed_n=hh["billed_n"], billed=hh["billed"], pending=p_["value"],
                          overdue=p_["overdue_value"], source=hh["source"]))
    prev = next((t for t in reversed(trend) if t["month"] < m), None)

    notes = []
    reg_only = [v for v in pvs if v["source"] == "Invoice register"]
    if reg_only and len(reg_only) == len(pvs):
        notes.append("This month's payments are from your invoice register only - debit notes and cash discount "
                     "are not known, so Net = invoice value. Fetch payments from TAFE Channel for this month "
                     "(Get data tab) for the full detail.")
    elif reg_only:
        notes.append(f"{len(reg_only)} voucher(s) worth Rs {sum(v['gross'] for v in reg_only):,.2f} are only in "
                     "your invoice register (not in the TAFE Channel export) - their deductions are not known.")
    if end >= date.today():
        notes.append(f"This month is still running - figures up to {date.today():%d-%b-%Y}.")
    if b["dates"]["pay_until"] and b["dates"]["pay_until"] < end.isoformat() and end < date.today():
        notes.append(f"Payment data only up to {b['dates']['pay_until']} - fetch payments for the rest of the month.")

    return dict(month=m, months=ms, label=start.strftime("%B %Y"), from_=start.isoformat(), to=end.isoformat(),
                summary=dict(payments=h["payments"], invoices=h["invoices"], gross=h["gross"],
                             debit_note=h["debit_note"], discount=h["discount"], other=h["other"], net=h["net"],
                             source=h["source"]),
                prev=prev, speed=speed, by_plant=by_plant, unassigned=unassigned, vouchers=pvs, by_week=by_week,
                billed=billed, pending=pend, pending_list=pend_list, invoices=invoices, deductions=deds,
                trend=trend, credit_days=b["credit_days"], notes=notes,
                tafe_from=b["tafe_from"], tafe_to=b["tafe_to"], pay_until=b["dates"]["pay_until"])
