"""Sales invoices straight from TallyPrime (no export by hand).

TallyPrime has a built-in XML server. Turn it on once on the PC that runs Tally:
    F1 Help > Settings > Connectivity > Client/Server configuration
    TallyPrime acts as: Both      Port: 9000
Keep Tally open with the company loaded. The hub then POSTs an XML request to http://localhost:9000 and
reads the Sales vouchers back - one request per company (location) and month.

Two ways of asking, tried in this order:
  1. a small TDL collection of Sales vouchers (fast, only the fields we need)
  2. the 'Day Book' report with every voucher exploded (works on every Tally version)
Both answers contain <VOUCHER> elements and are read by the same parser.
The last answer of every company is saved in data/tally/ so it can be checked by hand.
"""
import html
import os
import re
import threading
import traceback
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from ... import config
from ...supp.services.norm import part_key
from .norm import inv_key

STATUS = dict(running=False, log=[], started="", finished="", error="", result=None)
_lock = threading.Lock()
TIMEOUT = 180


def _log(msg):
    STATUS["log"].append(f"{datetime.now():%H:%M:%S}  {msg}")
    STATUS["log"] = STATUS["log"][-80:]
    print("[Tally]", msg)


def _tdate(d):
    return d.strftime("%d-%b-%Y")          # 01-Oct-2026


def _company_var(company):
    return f"<SVCURRENTCOMPANY>{html.escape(company)}</SVCURRENTCOMPANY>" if company else ""


def all_vouchers():
    """Setting 'Pull every voucher type' (on unless turned off): receipts, payments, journals ... come too,
    so Ore can keep and compare the whole books. TAFE sales invoices are picked out of them as before."""
    try:
        from .defaults import load_settings
        return bool(load_settings().get("tally_all_vouchers", True))
    except Exception:  # noqa: BLE001
        return True


def collection_request(company, d1, d2, all_types=None):
    all_types = all_vouchers() if all_types is None else all_types
    filt = "" if all_types else "\n    <FILTER>SDEWHubIsSales</FILTER>"
    return f"""<ENVELOPE>
 <HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>SDEWHubSales</ID></HEADER>
 <BODY><DESC>
  <STATICVARIABLES>
   <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>{_company_var(company)}
   <SVFROMDATE TYPE="Date">{_tdate(d1)}</SVFROMDATE><SVTODATE TYPE="Date">{_tdate(d2)}</SVTODATE>
  </STATICVARIABLES>
  <TDL><TDLMESSAGE>
   <COLLECTION NAME="SDEWHubSales" ISMODIFY="No">
    <TYPE>Voucher</TYPE>
    <FETCH>Date, VoucherNumber, VoucherTypeName, PartyLedgerName, Reference, IsCancelled, IsOptional</FETCH>
    <FETCH>GUID, Narration</FETCH>
    <FETCH>AllInventoryEntries.*, LedgerEntries.*, AllLedgerEntries.*, InvoiceOrderList.*</FETCH>{filt}
   </COLLECTION>
   <SYSTEM TYPE="Formulae" NAME="SDEWHubIsSales">$$IsSales:$VoucherTypeName</SYSTEM>
  </TDLMESSAGE></TDL>
 </DESC></BODY>
</ENVELOPE>"""


def daybook_request(company, d1, d2):
    return f"""<ENVELOPE>
 <HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Data</TYPE><ID>Day Book</ID></HEADER>
 <BODY><DESC><STATICVARIABLES>
   <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>{_company_var(company)}
   <SVFROMDATE TYPE="Date">{_tdate(d1)}</SVFROMDATE><SVTODATE TYPE="Date">{_tdate(d2)}</SVTODATE>
   <EXPLODEFLAG>Yes</EXPLODEFLAG>
 </STATICVARIABLES></DESC></BODY>
</ENVELOPE>"""


COMPANIES_REQUEST = """<ENVELOPE>
 <HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>SDEWHubCompanies</ID></HEADER>
 <BODY><DESC>
  <STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES>
  <TDL><TDLMESSAGE>
   <COLLECTION NAME="SDEWHubCompanies" ISMODIFY="No"><TYPE>Company</TYPE><FETCH>Name, StartingFrom</FETCH></COLLECTION>
  </TDLMESSAGE></TDL>
 </DESC></BODY>
</ENVELOPE>"""


# ----------------------------------------------------------------------------- talking to Tally
def post(url, xml, timeout=TIMEOUT):
    req = urllib.request.Request(url, data=xml.encode("utf-8"),
                                 headers={"Content-Type": "text/xml; charset=utf-8"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # Tally is on this PC / LAN: no proxy
    with opener.open(req, timeout=timeout) as resp:
        raw = resp.read()
    return decode(raw)


def decode(raw):
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    if len(raw) > 3 and raw[1:2] == b"\x00":
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("utf-8", errors="replace")


_BAD_REF = re.compile(r"&#(x[0-9a-fA-F]+|\d+);")
_PREFIXED_TAG = re.compile(r"<(/?)([A-Za-z_][\w.\-]*):")
_PREFIXED_ATTR = re.compile(r"(\s)([A-Za-z_][\w.\-]*):([A-Za-z_][\w.\-]*)=")
_BAD_CHR = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean_xml(text):
    """Tally writes characters XML does not allow (e.g. &#4; in names) - drop them before parsing."""
    def ok(m):
        v = m.group(1)
        n = int(v[1:], 16) if v[0] in "xX" else int(v)
        return m.group(0) if n in (9, 10, 13) or n >= 32 else ""
    text = _BAD_REF.sub(ok, text)
    text = _BAD_CHR.sub("", text)
    # Tally writes user-defined fields as <UDF:NAME ...> often WITHOUT declaring the UDF namespace
    # ("unbound prefix" for every XML reader). We never read those fields: turn the prefix into a plain name.
    text = _PREFIXED_TAG.sub(lambda m: f"<{m.group(1)}{m.group(2)}_", text)
    text = _PREFIXED_ATTR.sub(lambda m: f"{m.group(1)}{m.group(2)}_{m.group(3)}=", text)
    return text.lstrip("\ufeff").strip()


def tally_error(text):
    """Tally answers errors as <LINEERROR>...</LINEERROR> or plain text."""
    m = re.search(r"<LINEERROR>(.*?)</LINEERROR>", text, re.S)
    if m:
        return m.group(1).strip()
    if "<ENVELOPE" not in text.upper():
        return text.strip()[:300] or "Empty answer from Tally"
    return ""


def list_companies(url):
    text = clean_xml(post(url, COMPANIES_REQUEST, timeout=30))
    err = tally_error(text)
    if err:
        raise RuntimeError(err)
    root = ET.fromstring(text)
    names = []
    for c in root.iter("COMPANY"):
        n = c.get("NAME") or (c.findtext("NAME") or "").strip()
        if n and n not in names:
            names.append(n)
    return names


# ----------------------------------------------------------------------------- reading vouchers
def _t(el, tag):
    v = el.findtext(tag)
    return (v or "").strip()


def _num(s):
    m = re.search(r"-?[\d,]*\.?\d+", s or "")
    return float(m.group(0).replace(",", "")) if m else 0.0


def _date(s):
    s = (s or "").strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def _children(el, name):
    """Elements <NAME.LIST> (Tally list) directly under el."""
    return [c for c in el if c.tag == name + ".LIST"]


def _order_nos(el):
    out = []
    for tag in ("BASICPURCHASEORDERNO", "ORDERNO", "BASICORDERREF"):
        for o in el.iter(tag):
            v = (o.text or "").strip()
            if v and v.lower() not in ("any", "not applicable") and v not in out:
                out.append(v)
    return out


def parse_vouchers(text):
    """Tally XML -> list of sales invoices: dict(inv_no, inv_key, inv_date, party, amount, order_no, cancelled, lines)."""
    root = ET.fromstring(clean_xml(text))
    out = []
    for v in root.iter("VOUCHER"):
        vtype = v.get("VCHTYPE") or _t(v, "VOUCHERTYPENAME")
        no = _t(v, "VOUCHERNUMBER")
        if not no:
            continue
        party = _t(v, "PARTYLEDGERNAME") or _t(v, "PARTYNAME")
        lines, seq = [], 0
        for inv in _children(v, "ALLINVENTORYENTRIES") + _children(v, "INVENTORYENTRIES"):
            item = _t(inv, "STOCKITEMNAME")
            if not item:
                continue
            first = re.split(r"\s|-", item, 1)[0]
            qty = _num(_t(inv, "BILLEDQTY") or _t(inv, "ACTUALQTY"))
            rate = _num((_t(inv, "RATE") or "").split("/")[0])
            orders = _order_nos(inv)
            lines.append(dict(seq=seq, part=part_key(first), item_name=item, qty=abs(qty), rate=abs(rate),
                              amount=abs(_num(_t(inv, "AMOUNT"))), order_no=orders[0] if orders else ""))
            seq += 1
        amount = 0.0
        ledgers = _children(v, "LEDGERENTRIES") + _children(v, "ALLLEDGERENTRIES")
        for le in ledgers:
            if _t(le, "ISPARTYLEDGER").lower() == "yes" or (party and _t(le, "LEDGERNAME") == party):
                amount = abs(_num(_t(le, "AMOUNT")))
                break
        if not amount:
            amount = abs(_num(_t(v, "AMOUNT")))
        orders = _order_nos(v)
        out.append(dict(inv_no=no, inv_key=inv_key(no), inv_date=_date(_t(v, "DATE")), party=party,
                        vtype=vtype, amount=round(amount, 2),
                        order_no=orders[0] if orders else (lines[0]["order_no"] if lines else ""),
                        cancelled=1 if _t(v, "ISCANCELLED").lower() == "yes" or _t(v, "ISOPTIONAL").lower() == "yes" else 0,
                        lines=lines))
    return out


# ----------------------------------------------------------------------------- every voucher, with its ledger lines
def _money(text):
    """Tally amount text -> exact Decimal (2 places). Tally writes debit negative."""
    m = re.match(r"^\s*(-?[\d,]*\.?\d+)", text or "")
    if not m:
        return Decimal("0.00")
    try:
        return Decimal(m.group(1).replace(",", "")).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")


def _entries(v):
    """Ledger entries of a voucher. ALLLEDGERENTRIES, when Tally sends it, already holds every ledger, the sales or
    purchase ledger of the item lines included. Otherwise: LEDGERENTRIES plus the accounting allocations inside
    every item line. Never both, or amounts count twice."""
    every = _children(v, "ALLLEDGERENTRIES")
    if every:
        return every
    out = list(_children(v, "LEDGERENTRIES"))
    for item in _children(v, "ALLINVENTORYENTRIES") + _children(v, "INVENTORYENTRIES"):
        out += _children(item, "ACCOUNTINGALLOCATIONS")
    return out


def parse_full(text):
    """Tally XML -> every voucher: dict(guid, vtype, vno, vdate, party, reference, narration, cancelled, optional,
    lines=[(ledger, amount)] with amount a Decimal, debit positive)."""
    root = ET.fromstring(clean_xml(text))
    out = []
    for v in root.iter("VOUCHER"):
        vdate = _date(_t(v, "DATE"))
        if not vdate:
            continue
        sums, order = {}, []
        for e in _entries(v):
            name = _t(e, "LEDGERNAME")
            if not name:
                continue
            if name not in sums:
                sums[name] = Decimal("0.00")
                order.append(name)
            sums[name] -= _money(_t(e, "AMOUNT"))
        lines = [(n, sums[n]) for n in order if sums[n] != 0]
        out.append(dict(guid=_t(v, "GUID"), vtype=v.get("VCHTYPE") or _t(v, "VOUCHERTYPENAME"),
                        vno=_t(v, "VOUCHERNUMBER"), vdate=vdate, party=_t(v, "PARTYLEDGERNAME"),
                        reference=_t(v, "REFERENCE"), narration=_t(v, "NARRATION")[:500],
                        cancelled=1 if _t(v, "ISCANCELLED").lower() == "yes" or _t(v, "ISDELETED").lower() == "yes" else 0,
                        optional=1 if _t(v, "ISOPTIONAL").lower() == "yes" else 0, lines=lines))
    return out


def voucher_key(company, v):
    if v["guid"]:
        return f"{company}|{v['guid']}"
    return f"{company}|{v['vtype']}|{v['vno']}|{v['vdate']}"


def store_full(vouchers, company):
    """Every voucher and its ledger lines, replaced on every pull (a voucher altered in Tally is read again)."""
    from ..db import get_db
    if not vouchers:
        return 0
    con = get_db()
    now = datetime.now().isoformat(timespec="seconds")
    for v in vouchers:
        key = voucher_key(company, v)
        total = sum((a for _, a in v["lines"] if a > 0), Decimal("0.00"))
        con.execute("INSERT INTO gp_tally_vouchers(vkey, company, guid, vtype, vno, vdate, party, reference, narration, "
                    "cancelled, optional, total, pulled_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(vkey) DO UPDATE "
                    "SET company=excluded.company, guid=excluded.guid, vtype=excluded.vtype, vno=excluded.vno, "
                    "vdate=excluded.vdate, party=excluded.party, reference=excluded.reference, "
                    "narration=excluded.narration, cancelled=excluded.cancelled, optional=excluded.optional, "
                    "total=excluded.total, pulled_at=excluded.pulled_at",
                    (key, company, v["guid"], v["vtype"], v["vno"], v["vdate"], v["party"], v["reference"],
                     v["narration"], v["cancelled"], v["optional"], str(total), now))
        con.execute("DELETE FROM gp_tally_vlines WHERE vkey=?", (key,))
        for seq, (ledger, amount) in enumerate(v["lines"]):
            con.execute("INSERT INTO gp_tally_vlines(vkey, seq, ledger, amount) VALUES(?,?,?,?)",
                        (key, seq, ledger, str(amount)))
    con.commit()
    return len(vouchers)


def keep_full(text, company, a, b):
    """Store every voucher dated a..b in a Tally answer. Never stops the TAFE invoice pull if it fails."""
    try:
        vs = [x for x in parse_full(text) if a.isoformat() <= x["vdate"] <= b.isoformat()]
        n = store_full(vs, company)
        return n
    except Exception as e:  # noqa: BLE001
        _log(f"Could not keep the full vouchers ({e}); the TAFE invoices are still read")
        return 0


def is_sales(inv, parties):
    """Sales voucher of a TAFE party. Day Book also returns receipts, journals ... (no stock lines)."""
    t = (inv.get("vtype") or "").lower()
    if t and "sales" not in t and "invoice" not in t and "tax" not in t:
        return False
    return inv["party"] in parties if parties else True


# ----------------------------------------------------------------------------- storing
def store(invoices, company, source="Tally"):
    from ..db import get_db
    con = get_db()
    now = datetime.now().isoformat(timespec="seconds")
    for inv in invoices:
        con.execute("INSERT INTO gp_tally_invoices(inv_key, inv_no, inv_date, party, company, amount, order_no, "
                    "cancelled, source, pulled_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(inv_key) DO UPDATE SET "
                    "inv_no=excluded.inv_no, inv_date=excluded.inv_date, party=excluded.party, company=excluded.company, "
                    "amount=excluded.amount, order_no=excluded.order_no, cancelled=excluded.cancelled, "
                    "source=excluded.source, pulled_at=excluded.pulled_at",
                    (inv["inv_key"], inv["inv_no"], inv["inv_date"], inv["party"], company, inv["amount"],
                     inv["order_no"], inv["cancelled"], source, now))
        con.execute("DELETE FROM gp_tally_lines WHERE inv_key=?", (inv["inv_key"],))
        for ln in inv["lines"]:
            con.execute("INSERT INTO gp_tally_lines(inv_key, seq, part, item_name, qty, rate, amount, order_no) "
                        "VALUES(?,?,?,?,?,?,?,?)", (inv["inv_key"], ln["seq"], ln["part"], ln["item_name"],
                                                     ln["qty"], ln["rate"], ln["amount"], ln["order_no"]))
    con.commit()


def months(d1, d2):
    d = d1
    while d <= d2:
        nxt = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield d, min(d2, nxt - timedelta(days=1))
        d = nxt


def pull_company(url, company, d1, d2, parties):
    """-> (invoices kept, how they were asked). Raises with Tally's own message on errors."""
    out_dir = os.path.join(config.DATA_DIR, "tally")
    os.makedirs(out_dir, exist_ok=True)
    safe = re.sub(r"[^\w\-]", "_", company or "open_company")[:60]
    kept, how = [], ""
    for a, b in months(d1, d2):
        got = None
        for mode, build in (("collection", collection_request), ("day book", daybook_request)):
            text = post(url, build(company, a, b))
            with open(os.path.join(out_dir, f"last_{safe}_{mode.replace(' ', '')}.xml"), "w", encoding="utf-8") as fh:
                fh.write(text)
            err = tally_error(text)
            if err:
                if mode == "collection":
                    _log(f"{company or 'open company'} {a:%b-%Y}: collection request refused ({err[:120]}) - trying Day Book")
                    continue
                raise RuntimeError(err)
            vs = [x for x in parse_vouchers(text) if x["inv_date"] and a.isoformat() <= x["inv_date"] <= b.isoformat()]
            if (vs and any(x["lines"] or x["amount"] for x in vs)) or mode == "day book":
                got, how = vs, mode
                full = keep_full(text, company, a, b)
                if full:
                    _log(f"{company or 'open company'} {a:%b-%Y}: {full} vouchers kept with their ledger lines")
                break
        sales = [x for x in (got or []) if is_sales(x, parties)]
        kept += sales
        _log(f"{company or 'open company'} {a:%b-%Y}: {len(got or [])} vouchers, {len(sales)} TAFE sales invoices ({how})")
    return kept, how


def start(url, companies, d1, d2, parties):
    with _lock:
        if STATUS["running"]:
            return False
        STATUS.update(running=True, log=[], started=datetime.now().isoformat(timespec="seconds"), finished="",
                      error="", result=None)
    threading.Thread(target=_run, args=(url, companies, d1, d2, parties), daemon=True).start()
    return True


def _run(url, companies, d1, d2, parties):
    from ..db import log
    total, per = 0, []
    try:
        for comp in companies or [""]:
            name = comp.get("name", "") if isinstance(comp, dict) else comp
            _log(f"Reading {name or 'the company open in Tally'} {d1:%d-%b-%Y} to {d2:%d-%b-%Y}")
            invs, how = pull_company(url, name, d1, d2, parties)
            store(invs, name)
            per.append(dict(company=name or "(open company)", invoices=len(invs), how=how))
            total += len(invs)
        STATUS["result"] = dict(invoices=total, companies=per)
        log("grin", "Tally pull", f"{total} invoices {d1} to {d2}")
        _log(f"Done - {total} TAFE invoices read")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        msg = str(e)
        if "refused" in msg.lower() or "10061" in msg or "timed out" in msg.lower() or "urlopen error" in msg.lower():
            msg = (f"Tally is not answering on {url}. Open TallyPrime with the company loaded and turn on "
                   f"F1 Help > Settings > Connectivity > Client/Server: 'Both', port 9000. ({e})")
        STATUS["error"] = msg
        _log(f"Stopped: {msg}")
    finally:
        STATUS["running"] = False
        STATUS["finished"] = datetime.now().isoformat(timespec="seconds")


# ----------------------------------------------------------------------------- the website's pull (browser + bridge)
# On the website the BROWSER asks Tally, through tools/tally_bridge.py on the computer it runs on, so every
# computer pulls its own Tally. The server only builds the requests and reads the answers.
def chunks(d1, d2, days=None):
    """Week-sized pieces: a week's Tally answer stays well below Vercel's 4.5 MB request limit. With every
    voucher type the pieces are 3 days, as receipts, payments and journals come too."""
    days = days or (3 if all_vouchers() else 7)
    d = d1
    while d <= d2:
        e = min(d2, d + timedelta(days=days - 1))
        yield d, e
        d = e + timedelta(days=1)


def plan(companies, d1, d2):
    out = []
    for comp in companies or [""]:
        name = comp.get("name", "") if isinstance(comp, dict) else comp
        for a, b in chunks(d1, d2):
            out.append(dict(company=name, **{"from": a.isoformat()}, to=b.isoformat(),
                            collection=collection_request(name, a, b), daybook=daybook_request(name, a, b)))
    return out


def ingest_text(text, company, a, b, parties, mode):
    """One Tally answer from the browser -> stored. usable=False tells the browser to try the Day Book request."""
    err = tally_error(text)
    if err:
        return dict(ok=False, error=err, usable=False)
    vs = [x for x in parse_vouchers(text) if x["inv_date"] and a.isoformat() <= x["inv_date"] <= b.isoformat()]
    usable = (vs and any(x["lines"] or x["amount"] for x in vs)) or mode == "daybook"
    if not usable:
        return dict(ok=True, usable=False, vouchers=len(vs), invoices=0)
    sales = [x for x in vs if is_sales(x, parties)]
    store(sales, company)
    full = keep_full(text, company, a, b)
    return dict(ok=True, usable=True, vouchers=len(vs), invoices=len(sales), kept=full)
