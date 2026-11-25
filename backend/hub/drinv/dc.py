"""Delivery challans from Tally (DR -> Invoice > Admin > Pull DC from Tally).

Every "Delivery Note" voucher (SDEW's DC) between two dates is read from TallyPrime through the Tally bridge
(website) or by the PC hub itself, half a month per request, and kept in tally_dc / tally_dc_lines: DC number,
date, party, order / PO, narration, the Durga fields (NO OF PICES, NO OF PACKAGES, TOTAL NOS, Title, Party Name,
PO NUMBER) and every item line (part, qty, rate, amount, godown).
A period is replaced by what Tally sends for it, so DCs altered or deleted in Tally follow - except when Tally
sends nothing at all for a period the hub has DCs in (more likely a Tally hiccup than every DC deleted).
"""
import html
import re
from datetime import date, datetime, timedelta

from ..db import get_db, one, rows

DC_TYPES = ("Delivery Note",)
UDF = {"NOOFPICESDURGA": "pieces", "NOOFPACKSDURGA": "packages", "TOTALNOSDURGA": "total_nos",
       "DURGATITLE": "title", "DURGAPARTY": "party_name", "TAFPONO": "po_no"}
CHUNK_DAYS = 15


def _x(s):
    return html.escape(str(s or ""), quote=False)


def _tdate(d):
    return d.strftime("%d-%b-%Y")


def request(company, d1, d2, with_udf=True):
    comp = f"<SVCURRENTCOMPANY>{_x(company)}</SVCURRENTCOMPANY>" if company else ""
    # simple form (the fallback): only the voucher type name, no Durga fields - for a Tally that rejects either
    types = " OR ".join(f'$VoucherTypeName = "{t}"' for t in DC_TYPES)
    if with_udf:
        types += " OR $$IsDelNote:$VoucherTypeName"      # also DC types made under Delivery Note
    udf = f"<FETCH>{', '.join(UDF)}</FETCH>" if with_udf else ""
    return f"""<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE>
<ID>SDEWHubDC</ID></HEADER><BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>{comp}
<SVFROMDATE TYPE="Date">{_tdate(d1)}</SVFROMDATE><SVTODATE TYPE="Date">{_tdate(d2)}</SVTODATE></STATICVARIABLES>
<TDL><TDLMESSAGE><COLLECTION NAME="SDEWHubDC" ISMODIFY="No"><TYPE>Voucher</TYPE>
<FETCH>Date, VoucherNumber, VoucherTypeName, PartyLedgerName, Reference, Narration, IsCancelled, GUID, AlterID</FETCH>
<FETCH>AllInventoryEntries.*, InvoiceOrderList.*</FETCH>{udf}
<FILTER>SDEWHubIsDC</FILTER></COLLECTION>
<SYSTEM TYPE="Formulae" NAME="SDEWHubIsDC">{types}</SYSTEM></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"""


def plan(company, d1, d2):
    out, d = [], d1
    while d <= d2:
        e = min(d2, d + timedelta(days=CHUNK_DAYS - 1))
        out.append({"from": d.isoformat(), "to": e.isoformat(), "xml": request(company, d, e),
                    "xml_plain": request(company, d, e, with_udf=False)})
        d = e + timedelta(days=1)
    return out


def _t(v, tag):
    m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", v, re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def _num(s):
    m = re.search(r"-?[\d,]*\.?\d+", s or "")
    try:
        return float(m.group(0).replace(",", "")) if m else 0.0
    except ValueError:
        return 0.0


def _date(s):
    s = (s or "").strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return ""


def parse(text):
    """Tally's answer -> list of DCs with their item lines."""
    out = []
    for m in re.finditer(r"<VOUCHER\b([^>]*)>(.*?)</VOUCHER>", text or "", re.S):
        attrs, v = m.group(1), m.group(2)
        inv = re.findall(r"<ALLINVENTORYENTRIES\.LIST>(.*?)</ALLINVENTORYENTRIES\.LIST>", v, re.S)
        head = re.sub(r"<ALLINVENTORYENTRIES\.LIST>.*?</ALLINVENTORYENTRIES\.LIST>", "", v, flags=re.S)
        guid = _t(head, "GUID") or (re.search(r'REMOTEID="([^"]+)"', attrs) or [None, ""])[1]
        d = dict(guid=guid, vtype=_t(head, "VOUCHERTYPENAME") or (re.search(r'VCHTYPE="([^"]+)"', attrs) or [None, ""])[1],
                 vno=_t(head, "VOUCHERNUMBER"), vdate=_date(_t(head, "DATE")), party=_t(head, "PARTYLEDGERNAME"),
                 reference=_t(head, "REFERENCE"), narration=_t(head, "NARRATION"),
                 cancelled=1 if _t(head, "ISCANCELLED").lower() == "yes" else 0,
                 order_no=", ".join(dict.fromkeys(html.unescape(x).strip() for x in
                                                  re.findall(r"<BASICPURCHASEORDERNO>(.*?)</BASICPURCHASEORDERNO>", head)
                                                  if x.strip())),
                 alter_id=int(_num(_t(head, "ALTERID"))))
        for tag, key in UDF.items():
            mm = re.search(rf"<(?:UDF:)?{tag}\b[^>]*>([^<]*)</(?:UDF:)?{tag}>", head)
            d[key] = html.unescape(mm.group(1)).strip() if mm else ""
        lines = []
        for i, b in enumerate(inv):
            item = _t(b, "STOCKITEMNAME")
            qty_s = _t(b, "BILLEDQTY") or _t(b, "ACTUALQTY")
            unit = (re.search(r"[\d.]+\s*([A-Za-z.]+)", qty_s) or [None, ""])[1]
            order = _t(b, "ORDERNO")
            lines.append(dict(seq=i, item=item, part=(re.match(r"\s*([0-9A-Z]{5,})", item.upper()) or [None, ""])[1],
                              qty=_num(qty_s), unit=unit, rate=_num(_t(b, "RATE")), amount=abs(_num(_t(b, "AMOUNT"))),
                              godown=_t(b, "GODOWNNAME"),
                              order_no="" if "applicable" in order.lower() else order))
        d["lines"] = lines
        d["qty"] = sum(x["qty"] for x in lines)
        d["amount"] = sum(x["amount"] for x in lines)
        d["vkey"] = d["guid"] or f"{d['vtype']}|{d['vno']}|{d['vdate']}"
        if d["vno"] or d["guid"]:
            out.append(d)
    return out


def save(text, d1, d2):
    """Store one period. -> report."""
    err = re.search(r"<LINEERROR>(.*?)</LINEERROR>", text or "", re.S)
    if err:
        return dict(ok=False, error=html.unescape(err.group(1)).strip())
    dcs = [x for x in parse(text) if not x["vdate"] or d1 <= x["vdate"] <= d2]
    con = get_db()
    have = one("SELECT COUNT(*) n FROM tally_dc WHERE vdate BETWEEN ? AND ?", (d1, d2))["n"]
    if not dcs and have:
        return dict(ok=True, dcs=0, kept=have, note=f"Tally sent no DC for {d1} to {d2}; the hub's {have} kept")
    old = [r["vkey"] for r in rows("SELECT vkey FROM tally_dc WHERE vdate BETWEEN ? AND ?", (d1, d2))]
    for i in range(0, len(old), 200):
        part = old[i:i + 200]
        q = ",".join("?" * len(part))
        con.execute(f"DELETE FROM tally_dc_lines WHERE vkey IN ({q})", tuple(part))
    con.execute("DELETE FROM tally_dc WHERE vdate BETWEEN ? AND ?", (d1, d2))
    now = datetime.now().isoformat(timespec="seconds")
    cols = ["vkey", "guid", "vtype", "vno", "vdate", "party", "reference", "order_no", "narration", "cancelled",
            "pieces", "packages", "total_nos", "title", "party_name", "po_no", "qty", "amount", "alter_id"]
    con.executemany(f"INSERT OR REPLACE INTO tally_dc({','.join(cols)}, pulled_at) VALUES({','.join('?' * len(cols))},?)",
                    [tuple(x[c] for c in cols) + (now,) for x in dcs])
    con.executemany("INSERT OR REPLACE INTO tally_dc_lines(vkey, seq, item, part, qty, unit, rate, amount, godown, order_no) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    [(x["vkey"], ln["seq"], ln["item"], ln["part"], ln["qty"], ln["unit"], ln["rate"], ln["amount"],
                      ln["godown"], ln["order_no"]) for x in dcs for ln in x["lines"]])
    con.commit()
    return dict(ok=True, dcs=len(dcs), lines=sum(len(x["lines"]) for x in dcs), replaced=len(old),
                with_fields=sum(1 for x in dcs if x["pieces"] or x["packages"] or x["total_nos"]))


def listing(q="", limit=300):
    where, args = "", ()
    if q:
        like = f"%{q.strip()}%"
        where = ("WHERE d.vno LIKE ? OR d.party LIKE ? OR d.narration LIKE ? OR d.order_no LIKE ? OR d.po_no LIKE ? "
                 "OR d.vkey IN (SELECT vkey FROM tally_dc_lines WHERE part LIKE ? OR item LIKE ?)")
        args = (like,) * 7
    dcs = rows(f"SELECT d.* FROM tally_dc d {where} ORDER BY d.vdate DESC, d.vno DESC LIMIT ?", args + (limit,))
    keys = [d["vkey"] for d in dcs]
    lines = {}
    for i in range(0, len(keys), 200):
        part = keys[i:i + 200]
        for ln in rows(f"SELECT * FROM tally_dc_lines WHERE vkey IN ({','.join('?' * len(part))}) ORDER BY vkey, seq",
                       tuple(part)):
            lines.setdefault(ln["vkey"], []).append(ln)
    for d in dcs:
        d["lines"] = lines.get(d["vkey"], [])
    s = one("SELECT COUNT(*) n, MIN(vdate) first, MAX(vdate) last, MAX(pulled_at) pulled, "
            "SUM(cancelled) cancelled FROM tally_dc") or {}
    return dict(dcs=dcs, summary=s)
