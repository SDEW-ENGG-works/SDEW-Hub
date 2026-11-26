"""Groups, ledgers with their balances, and the stock summary straight from TallyPrime, next to the voucher
pull, so Ore can work out the Profit and loss, Trial balance and Balance sheet from Tally's own data.

What is asked, per company (each through Tally's XML server, like the vouchers in tally.py):
  * groups:   every group with its parent and Tally's flags (revenue, affects gross profit), one request;
  * ledgers:  every ledger with its group, GSTIN and bill-wise flag, and its balance on each date below;
  * stock:    the stock summary (closing quantity and value of every stock item) on each date below.
The dates: the day before From (opening), every month end in between, and To. The ledger balances on those
dates are Tally's own trial balance, the stock values Tally's closing stock, so Ore's sums can be checked.

Amounts: Tally writes a debit as a minus number. Here every amount is turned round so debit is positive, the
same as the voucher lines (gp_tally_vlines), and the text Tally sent is kept beside it (raw) for checking.
A request Tally refuses is asked again with fewer fields; a failure here never stops the voucher pull.
"""
import html
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from .tally import clean_xml, post, tally_error

KINDS = ("groups", "ledgers", "stock")


def _tdate(d):
    return d.strftime("%d-%b-%Y")


def _fy_start(d):
    return date(d.year if d.month >= 4 else d.year - 1, 4, 1)


def _company_var(company):
    return f"<SVCURRENTCOMPANY>{html.escape(company)}</SVCURRENTCOMPANY>" if company else ""


def _collection(cid, typ, fetch, company, as_on=None):
    dates = ""
    if as_on:
        dates = (f"\n   <SVFROMDATE TYPE=\"Date\">{_tdate(_fy_start(as_on))}</SVFROMDATE>"
                 f"<SVTODATE TYPE=\"Date\">{_tdate(as_on)}</SVTODATE>")
    return f"""<ENVELOPE>
 <HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>{cid}</ID></HEADER>
 <BODY><DESC>
  <STATICVARIABLES>
   <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>{_company_var(company)}{dates}
  </STATICVARIABLES>
  <TDL><TDLMESSAGE>
   <COLLECTION NAME="{cid}" ISMODIFY="No"><TYPE>{typ}</TYPE><FETCH>{fetch}</FETCH></COLLECTION>
  </TDLMESSAGE></TDL>
 </DESC></BODY>
</ENVELOPE>"""


# Each kind: the full field list first, then a shorter one for older Tally releases that refuse a field.
FETCH = {
    "groups": ("Group", ["Name, Parent, IsRevenue, AffectsGrossProfit, IsDeemedPositive", "Name, Parent"]),
    "ledgers": ("Ledger", ["Name, Parent, OpeningBalance, ClosingBalance, PartyGSTIN, IsBillWiseOn",
                           "Name, Parent, OpeningBalance, ClosingBalance"]),
    "stock": ("StockItem", ["Name, Parent, BaseUnits, ClosingBalance, ClosingValue",
                            "Name, ClosingBalance, ClosingValue"]),
}


def requests_for(kind, company, as_on=None):
    typ, fetches = FETCH[kind]
    return [_collection(f"SDEWHub{typ}s", typ, f, company, None if kind == "groups" else as_on) for f in fetches]


def balance_dates(d1, d2):
    """The day before d1, every month end from d1 to d2, and d2."""
    out = [d1 - timedelta(days=1)]
    d = d1
    while True:
        end = (d.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        if end >= d2:
            break
        out.append(end)
        d = end + timedelta(days=1)
    out.append(d2)
    return sorted(set(out))


def plan(companies, d1, d2):
    """Every masters request for the website's pull (the browser sends each to Tally through the bridge)."""
    out = []
    for comp in companies or [""]:
        name = comp.get("name", "") if isinstance(comp, dict) else comp
        out.append(dict(kind="groups", company=name, as_on="", requests=requests_for("groups", name)))
        for on in balance_dates(d1, d2):
            for kind in ("ledgers", "stock"):
                out.append(dict(kind=kind, company=name, as_on=on.isoformat(), requests=requests_for(kind, name, on)))
    return out


# ----------------------------------------------------------------------------- reading the answers
def _t(el, tag):
    v = el.findtext(tag)
    return (v or "").strip()


def _name(el):
    n = (el.get("NAME") or "").strip()
    if not n:
        n = _t(el, "NAME") or (el.findtext("NAME.LIST/NAME") or "").strip()
    return n.strip()


def _yes(el, tag):
    return 1 if _t(el, tag).lower() == "yes" else 0


def amount(text):
    """Tally amount text -> Decimal with debit positive. '-1234.50' is a debit; '1234.50 Dr' / 'Cr' are honoured."""
    s = (text or "").strip()
    m = re.search(r"-?[\d,]*\.?\d+", s)
    if not m:
        return Decimal("0.00")
    try:
        v = Decimal(m.group(0).replace(",", "")).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")
    low = s.lower()
    if low.endswith("dr"):
        return abs(v)
    if low.endswith("cr"):
        return -abs(v)
    return -v


def quantity(text):
    """'120.500 Nos' -> (Decimal('120.500'), 'Nos'). Tally writes a negative stock as a minus number."""
    s = (text or "").strip()
    m = re.match(r"^\s*(-?[\d,]*\.?\d+)\s*(.*)$", s)
    if not m:
        return Decimal("0"), ""
    try:
        q = Decimal(m.group(1).replace(",", ""))
    except InvalidOperation:
        q = Decimal("0")
    return q, m.group(2).strip()


def _root(text):
    err = tally_error(text)
    if err:
        raise RuntimeError(err)
    return ET.fromstring(clean_xml(text))


def parse(kind, text):
    root = _root(text)
    out = []
    if kind == "groups":
        for g in root.iter("GROUP"):
            n = _name(g)
            if n:
                parent = _t(g, "PARENT")
                out.append(dict(name=n, parent="" if parent.lower() in ("", "primary") else parent,
                                is_revenue=_yes(g, "ISREVENUE"), affects_gp=_yes(g, "AFFECTSGROSSPROFIT"),
                                deemed_positive=_yes(g, "ISDEEMEDPOSITIVE")))
    elif kind == "ledgers":
        for le in root.iter("LEDGER"):
            n = _name(le)
            if n:
                out.append(dict(name=n, parent=_t(le, "PARENT"), gstin=_t(le, "PARTYGSTIN"),
                                bill_wise=_yes(le, "ISBILLWISEON"),
                                opening=amount(_t(le, "OPENINGBALANCE")), opening_raw=_t(le, "OPENINGBALANCE"),
                                balance=amount(_t(le, "CLOSINGBALANCE")), raw=_t(le, "CLOSINGBALANCE")))
    else:
        for it in root.iter("STOCKITEM"):
            n = _name(it)
            if not n:
                continue
            qty, unit = quantity(_t(it, "CLOSINGBALANCE"))
            out.append(dict(name=n, parent=_t(it, "PARENT"), unit=_t(it, "BASEUNITS") or unit, qty=qty,
                            value=amount(_t(it, "CLOSINGVALUE")), raw=_t(it, "CLOSINGVALUE")))
    return out


# ----------------------------------------------------------------------------- storing
def store(kind, items, company, as_on=None):
    """One answer -> its table. The rows of that company (and date) are replaced as a whole, so a ledger or item
    deleted in Tally goes too."""
    company = company or ""
    from ..db import get_db
    con = get_db()
    now = datetime.now().isoformat(timespec="seconds")
    if kind == "groups":
        con.execute("DELETE FROM gp_tally_groups WHERE company=?", (company,))
        con.executemany("INSERT INTO gp_tally_groups(company, name, parent, is_revenue, affects_gp, deemed_positive, "
                        "pulled_at) VALUES(?,?,?,?,?,?,?)",
                        [(company, g["name"], g["parent"], g["is_revenue"], g["affects_gp"], g["deemed_positive"], now)
                         for g in items])
    elif kind == "ledgers":
        con.execute("DELETE FROM gp_tally_ledgers WHERE company=?", (company,))
        con.executemany("INSERT INTO gp_tally_ledgers(company, name, parent, gstin, bill_wise, opening, opening_raw, "
                        "pulled_at) VALUES(?,?,?,?,?,?,?,?)",
                        [(company, x["name"], x["parent"], x["gstin"], x["bill_wise"], str(x["opening"]),
                          x["opening_raw"], now) for x in items])
        con.execute("DELETE FROM gp_tally_balances WHERE company=? AND as_on=?", (company, as_on))
        con.executemany("INSERT INTO gp_tally_balances(company, as_on, ledger, balance, raw, pulled_at) "
                        "VALUES(?,?,?,?,?,?)",
                        [(company, as_on, x["name"], str(x["balance"]), x["raw"], now) for x in items
                         if x["balance"] or x["raw"]])
    else:
        con.execute("DELETE FROM gp_tally_stock WHERE company=? AND as_on=?", (company, as_on))
        con.executemany("INSERT INTO gp_tally_stock(company, as_on, item, parent, unit, qty, value, raw, pulled_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        [(company, as_on, x["name"], x["parent"], x["unit"], str(x["qty"]), str(x["value"]), x["raw"], now)
                         for x in items if x["qty"] or x["value"]])
    con.commit()


def ingest(kind, text, company, as_on=""):
    """One Tally answer (from the PC pull or the website's bridge) -> stored. Returns what was kept."""
    if kind not in KINDS:
        raise ValueError(f"Unknown kind {kind}")
    items = parse(kind, text)
    store(kind, items, company, as_on or None)
    out = dict(kind=kind, as_on=as_on, rows=len(items))
    if kind == "stock":
        out["value"] = str(sum((x["value"] for x in items), Decimal("0.00")))
    return out


def pull(url, company, d1, d2, log=print):
    """The PC hub's pull: every request for one company. Never raises: the vouchers matter more."""
    done = dict(groups=0, ledgers=0, balance_dates=0, stock_dates=0)
    for item in plan([company], d1, d2):
        kind, on = item["kind"], item["as_on"]
        last = ""
        for xml in item["requests"]:
            try:
                r = ingest(kind, post(url, xml), company, on)
                if kind == "groups":
                    done["groups"] = r["rows"]
                elif kind == "ledgers":
                    done["ledgers"] = r["rows"]
                    done["balance_dates"] += 1
                else:
                    done["stock_dates"] += 1
                    log(f"{company or 'open company'} stock on {on}: {r['rows']} items, value {r['value']}")
                last = ""
                break
            except Exception as e:  # noqa: BLE001
                last = str(e)
        if last:
            log(f"{company or 'open company'}: could not read Tally {kind}{' on ' + on if on else ''} ({last[:150]})")
    log(f"{company or 'open company'}: {done['groups']} groups, {done['ledgers']} ledgers, balances on "
        f"{done['balance_dates']} dates, stock on {done['stock_dates']} dates")
    return done


def status():
    """What the hub holds, for the Sources page."""
    from ..db import rows
    def one(sql):
        r = rows(sql)
        return r[0] if r else {}
    return dict(groups=one("SELECT COUNT(*) n, MAX(pulled_at) pulled FROM gp_tally_groups"),
                ledgers=one("SELECT COUNT(*) n, MAX(pulled_at) pulled FROM gp_tally_ledgers"),
                balances=one("SELECT COUNT(DISTINCT as_on) dates, MIN(as_on) first, MAX(as_on) last FROM gp_tally_balances"),
                stock=one("SELECT COUNT(DISTINCT as_on) dates, MIN(as_on) first, MAX(as_on) last FROM gp_tally_stock"))
