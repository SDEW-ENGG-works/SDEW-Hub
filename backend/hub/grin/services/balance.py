"""TAFE outstanding: what TAFE's books say it owes us (Account Balance-Outstanding, fetched daily) set against our
own invoices, GRINs and payments - for the dashboard on the Status page.

  TAFE owes (their books)  = credit lines (our invoices booked, RF/RG) - debit lines (their debit notes, ZK)
  Expected this week       = booked invoices whose usual payment day (GRIN date + the days TAFE usually takes,
                             worked out from our payment data) falls on or before this Sunday; their debit notes
                             come off the same payment
  Received this week       = payments dated Monday..today (payment data) and lines that left TAFE's list since the
                             last fetch before Monday
  Not in TAFE's books yet  = invoices we see GRINed and unpaid that TAFE has not booked, plus invoices not GRINed
  Total to receive         = TAFE owes + not in their books yet
"""
import json
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta

from ..db import get_db, one, rows
from .norm import inv_key

GRINED_UNPAID = ("Awaiting payment", "Payment overdue", "GRIN short / rejected")
NOT_GRINED = ("Not GRINed", "GRIN pending")


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def store(got, source="manual"):
    lines = got["lines"]
    credit = round(sum(x["credit"] for x in lines), 2)
    debit = round(sum(x["debit"] for x in lines), 2)
    gen = next((b for b in got["balances"] if b["name"] == got.get("general")), None)
    net = round(sum(b["amount"] for b in got["balances"]), 2)
    now = datetime.now()
    con = get_db()
    cur = con.execute("INSERT INTO gp_bal_runs(fetched_at, fetch_date, source, owed, credit, debit, general, net, "
                      "balances, lines) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (now.isoformat(timespec="seconds"), now.date().isoformat(), source, round(credit - debit, 2), credit,
                       debit, gen["amount"] if gen else None, net, json.dumps(got["balances"]), len(lines)))
    rid = cur.lastrowid
    if not rid:
        rid = one("SELECT MAX(id) id FROM gp_bal_runs")["id"]
    for i, x in enumerate(lines):
        con.execute("INSERT INTO gp_bal_lines(run_id, seq, doc_no, line, doc_date, doc_type, grin_date, ref, inv_key, "
                    "debit, credit, narration) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rid, i, x["doc_no"], x["line"], x["doc_date"], x["doc_type"], x["grin_date"], x["ref"],
                     inv_key(x["ref"]), x["debit"], x["credit"], x["narration"]))
    # keep the lines of the last 120 days (the totals of every run stay)
    old = (now - timedelta(days=120)).isoformat(timespec="seconds")
    con.execute("DELETE FROM gp_bal_lines WHERE run_id IN (SELECT id FROM gp_bal_runs WHERE fetched_at < ?)", (old,))
    con.commit()
    return dict(run_id=rid, owed=round(credit - debit, 2), credit=credit, debit=debit, lines=len(lines),
                general=gen["amount"] if gen else None, net=net)


def last_fetch_date():
    r = one("SELECT MAX(fetch_date) d FROM gp_bal_runs")
    return (r or {}).get("d") or ""


def _lag(rows_, today):
    """Days TAFE usually takes from GRIN to payment (median of the last 120 days), at least 1."""
    since = (today - timedelta(days=120)).isoformat()
    d = [(_d(r["pv_date"]) - _d(r["grin_date"])).days for r in rows_
         if r.get("pv_date") and r.get("grin_date") and r["pv_date"] >= since and _d(r["pv_date"]) and _d(r["grin_date"])]
    d = [x for x in d if 0 <= x <= 90]
    return (max(1, int(round(statistics.median(d)))), len(d)) if len(d) >= 20 else (9, len(d))


def dashboard():
    from . import status as st
    run = one("SELECT * FROM gp_bal_runs ORDER BY id DESC LIMIT 1")
    data = st.build()
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    credit_days = data["settings"]["credit_days"]
    by_key = {r["inv_key"]: r for r in data["rows"]}
    lag, lag_n = _lag(data["rows"], today)
    out = dict(today=today.isoformat(), week_from=monday.isoformat(), week_to=sunday.isoformat(), lag=lag, lag_n=lag_n,
               credit_days=credit_days, run=None)

    # ---- received this week (our payment data)
    rec = [r for r in data["rows"] if r.get("pv_date") and monday.isoformat() <= r["pv_date"] <= today.isoformat()]
    out["received"] = dict(n=len(rec), value=round(sum((r["credit"] or r["amount"] or 0) for r in rec), 2),
                           pay_until=data["dates"]["pay_until"])

    # ---- not GRINed (never in TAFE's books before a GRIN)
    ng = [r for r in data["rows"] if r["status"] in NOT_GRINED]
    if not run:
        gu = [r for r in data["rows"] if r["status"] in GRINED_UNPAID]
        out.update(owed=None, not_booked=dict(n=len(gu), value=round(sum(r["amount"] or 0 for r in gu), 2)),
                   not_grined=dict(n=len(ng), value=round(sum(r["amount"] or 0 for r in ng), 2)))
        return out

    lines = rows("SELECT * FROM gp_bal_lines WHERE run_id=? ORDER BY seq", (run["id"],))
    out["run"] = dict(fetched_at=run["fetched_at"], source=run["source"], owed=run["owed"], credit=run["credit"],
                      debit=run["debit"], general=run["general"], net=run["net"], lines=run["lines"],
                      balances=[b for b in json.loads(run["balances"] or "[]")])
    booked_keys = {x["inv_key"] for x in lines if x["credit"]}

    # ---- every TAFE line with our view of it
    week, later, late, debits, mismatch, items = [], [], [], [], [], []
    for x in lines:
        r = by_key.get(x["inv_key"])
        gd = _d(x["grin_date"]) or _d(r["grin_date"] if r else "") or _d(x["doc_date"])
        exp = gd + timedelta(days=lag) if gd else today
        due = gd + timedelta(days=credit_days) if gd else None
        it = dict(doc_no=x["doc_no"], doc_type=x["doc_type"], doc_date=x["doc_date"], grin_date=x["grin_date"],
                  ref=x["ref"], amount=round((x["credit"] or 0) - (x["debit"] or 0), 2), narration=x["narration"],
                  plant=r["plant"] if r else "", our_status=r["status"] if r else "", our_value=r["amount"] if r else None,
                  expected=exp.isoformat(), due=due.isoformat() if due else "",
                  late_days=(today - due).days if due and due < today else 0, pv=r["pv"] if r else "")
        if x["debit"] and not x["credit"]:
            it["bucket"] = "Debit note"
            debits.append(it)
        elif due and due < today:
            it["bucket"] = "Overdue"
            late.append(it)
        elif exp <= sunday:
            it["bucket"] = "This week"
            week.append(it)
        else:
            it["bucket"] = "Later"
            later.append(it)
        if r and r["status"] == "Paid":
            it["flag"] = f"Our data says paid ({r['pv']} {r['pv_date']})"
            mismatch.append(it)
        elif not r and x["credit"]:
            it["flag"] = "Not in our invoice data (old year / other party?)"
        items.append(it)

    s = lambda L: round(sum(i["amount"] for i in L), 2)  # noqa: E731
    out["owed"] = run["owed"]
    out["this_week"] = dict(n=len(week) + len(late), value=round(s(week) + s(late) + s(debits), 2),
                            on_time=s(week), late=s(late), late_n=len(late), debits=s(debits), debits_n=len(debits))
    out["later"] = dict(n=len(later), value=s(later))
    out["mismatch"] = dict(n=len(mismatch), value=s(mismatch))

    # ---- GRINed and unpaid in our data, but TAFE has not booked it
    gu = [r for r in data["rows"] if r["status"] in GRINED_UNPAID and r["inv_key"] not in booked_keys]
    nb = [dict(ref=r["inv_no"], inv_date=r["inv_date"], plant=r["plant"], amount=r["amount"] or 0, grin_date=r["grin_date"],
               our_status=r["status"], days=(today - _d(r["grin_date"])).days if _d(r["grin_date"]) else None,
               bucket="GRINed, not booked by TAFE") for r in gu]
    nb += [dict(ref=r["inv_no"], inv_date=r["inv_date"], plant=r["plant"], amount=r["amount"] or 0, grin_date="",
                our_status=r["status"], days=r["age"], bucket="Not GRINed yet") for r in ng]
    out["not_booked"] = dict(n=len(gu), value=round(sum(r["amount"] or 0 for r in gu), 2))
    out["not_grined"] = dict(n=len(ng), value=round(sum(r["amount"] or 0 for r in ng), 2))
    out["total_due"] = round(run["owed"] + out["not_booked"]["value"] + out["not_grined"]["value"], 2)

    # ---- lines that left TAFE's list this week (= paid / adjusted), from the snapshots
    base = one("SELECT id, fetched_at FROM gp_bal_runs WHERE fetch_date < ? ORDER BY id DESC LIMIT 1", (monday.isoformat(),)) \
        or one("SELECT id, fetched_at FROM gp_bal_runs WHERE fetch_date >= ? ORDER BY id LIMIT 1", (monday.isoformat(),))
    cleared = dict(n=0, value=0.0, since="")
    if base and base["id"] != run["id"]:
        now_set = {(x["doc_no"], x["line"]) for x in lines}
        gone = [x for x in rows("SELECT * FROM gp_bal_lines WHERE run_id=?", (base["id"],))
                if (x["doc_no"], x["line"]) not in now_set]
        cleared = dict(n=len(gone), value=round(sum((x["credit"] or 0) - (x["debit"] or 0) for x in gone), 2),
                       since=base["fetched_at"])
    out["cleared"] = cleared

    # ---- trend: the last fetch of each day
    tr = rows("SELECT fetch_date, owed, lines FROM gp_bal_runs WHERE id IN (SELECT MAX(id) FROM gp_bal_runs "
              "GROUP BY fetch_date) ORDER BY fetch_date DESC LIMIT 21")
    out["trend"] = list(reversed(tr))
    prev = next((t for t in tr if t["fetch_date"] < run["fetch_date"]), None)
    out["prev"] = prev
    order = {"Overdue": 0, "This week": 1, "Debit note": 2, "Later": 3}
    items.sort(key=lambda i: (order.get(i["bucket"], 9), i["expected"], i["ref"]))
    nb.sort(key=lambda i: (i["bucket"], -(i["days"] or 0)))
    out["items"] = items
    out["not_booked_items"] = nb[:1500]
    return out
