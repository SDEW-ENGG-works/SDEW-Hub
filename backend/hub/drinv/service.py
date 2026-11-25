"""DR -> Invoice: drafts from Delivery Requests, checks, totals, and the Tally voucher XML."""
import html
import json
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from ..db import get_db, get_setting, one, rows, set_setting
from ..dqms.services import dr_pdf
from ..supp.services.po_parser import price_on

CFG_KEY = "drinv.config"
# Ledgers as used in Tally's GST SALES NEW vouchers for TAFE (read from the pulled Tally books)
DEFAULT = dict(
    vtype="GST SALES NEW", round_off="Round Off", cgst="Output CGST", sgst="Output SGST", igst="Output IGST",
    unit="QTY", godown="FINISHED GOODS", company="", last_learn="",
    plants=dict(
        MDU=dict(party="Tractors and Farm Equpment Ltd", inter=False,
                 sales={"5": "GST SALES @ 5%", "18": "GST Sales 18%"},
                 address=["No : 10/205, Kalladipatti P.O,", "Dindugal ( Dist )", "Madurai - 624201"],
                 state="Tamil Nadu", pincode="624201", gstin="33AAACT2761Q1Z1", place="MADURAI.",
                 cst="3414", tin="33111500330", durgaparty="TAFE/MDU"),
        DBR=dict(party="Tractors and Farm Equipment Ltd - B", inter=True,
                 sales={"5": "GST SALES INTERSTATE @ 5%", "18": "GST SALES INTERSTATE @ 18%"},
                 address=["Plot No : 1, Kiadb Industrial Area,", "Doddabalapur,", "Bangalore  - 561203"],
                 state="Karnataka", pincode="561203", gstin="29AAACT2761Q1ZQ", place="BANGALORE.",
                 cst="00750293", tin="29650081474", durgaparty="TAFE/DBR"),
    ),
    templates={},       # per plant: what a real invoice in Tally carries (UDF fields, party details) - learn()
)
# HSN 73181500 (banjo bolts) and 84099941 (breather) are 18 %; tractor parts 8708xxxx are 5 %
GST18 = {"0714224M02", "0714315M03", "1812P03001"}
EWAY_LIMIT = 50000
EDITABLE = ("inv_no", "inv_date", "qty", "pieces", "packages", "kgs", "rate", "remarks", "item_name", "gst_rate",
            "title")
DEFAULT_TITLE = "KANBAN"
VENDOR_CODE = "DS1615"           # SDEW's TAFE vendor code (TAFE Key ID: DS1615$PO$invoice$date)

# How SDEW's Tally keeps a TAFE invoice - read from real invoices 15621, 15622, 15554, 15495 (MDU),
# 15611, 15624, 15594 (DBR) with "Read Tally structure" on 25 Nov 2026.
# The TDL fields on the invoice (name in Tally, its number, what goes in):
VOUCHER_UDF = [   # (tag, DESC, INDEX, role)
    ("UDF:DURGAPARTY", "DurgaParty", 2986, "durgaparty"),     # Party Name: TAFE/MDU, TAFE/DBR
    ("UDF:DURGATITLE", "durgatitle", 8772, "title"),          # Title: KANBAN
    ("UDF:NOOFPICESDURGA", "noofpicesdurga", 8773, "pieces"),  # NO OF PICES
    ("UDF:NOOFPACKSDURGA", "noofpacksdurga", 8774, "packages"),  # NO OF PACKAGES
    ("UDF:TOTALNOSDURGA", "totalnosdurga", 8775, "qty"),       # TOTAL NOS
    ("UDF:APPUNIQUEID", "AppUniqueID", 25452, "appid"),        # TAFE Key ID
    ("UDF:TAFPONO", "TAFPONO", 25462, "po"),                   # PO NUMBER
]
ITEM_UDF = [
    ("UDF:NOOFRATE", "noofRate", 2984, "rate"),
    ("UDF:TAFEPARTNONEW", "TAFEPARTNONew", 25460, "part"),
]
# Order date on the invoice (Order Details): what the office types, not the PO's own date
PO_ORDER_DATE = {"1030000676": "20170701", "1210000691": "20170701"}


def log_event(action, detail, invoices=None):
    """History box: who uploaded / verified / sent what, and when."""
    try:
        get_db().execute("INSERT INTO drinv_log(at, user, action, detail, invoices) VALUES(?,?,?,?,?)",
                         (_now(), _user(), action, detail, json.dumps(invoices or [])))
        get_db().commit()
    except Exception:  # noqa: BLE001
        pass


def history_log(limit=200):
    out = []
    for r in rows("SELECT * FROM drinv_log ORDER BY id DESC LIMIT ?", (limit,)):
        r = dict(r)
        r["invoices"] = json.loads(r.get("invoices") or "[]")
        out.append(r)
    return out


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _user():
    try:
        from ..db import CURRENT_USER
        return CURRENT_USER.get() or ""
    except Exception:  # noqa: BLE001
        return ""


def D(v):
    return Decimal(str(v or 0))


def r2(v):
    return float(D(v).quantize(Decimal("0.01"), ROUND_HALF_UP))


def config():
    c = json.loads(json.dumps(DEFAULT))
    saved = get_setting(CFG_KEY) or {}
    for k, v in saved.items():
        if k == "plants":
            for p, pv in (v or {}).items():
                c["plants"].setdefault(p, {}).update(pv)
        else:
            c[k] = v
    if not c.get("company"):
        try:
            from ..grin.services.defaults import load_settings
            comps = load_settings().get("tally_companies") or []
            if comps:
                c["company"] = comps[0].get("name", "") if isinstance(comps[0], dict) else comps[0]
        except Exception:  # noqa: BLE001
            pass
    return c


def save_config(patch):
    saved = get_setting(CFG_KEY) or {}
    for k, v in (patch or {}).items():
        if k == "plants":
            for p, pv in (v or {}).items():
                saved.setdefault("plants", {}).setdefault(p, {}).update(pv)
        elif k in DEFAULT:
            saved[k] = v
    set_setting(CFG_KEY, saved)
    return config()


# ---------------------------------------------------------------- what Tally already knows about each part
def history(parts):
    """part -> dict(item_name, gst, last_rate, last_inv, crate, lid, carton) from the newest TAFE invoice in Tally."""
    parts = sorted({p for p in parts if p})
    out = {}
    if not parts:
        return out
    q = ",".join("?" * len(parts))
    hits = rows(
        f"SELECT l.part, l.item_name, l.rate, i.inv_no, i.inv_date FROM gp_tally_lines l "
        f"JOIN gp_tally_invoices i ON i.inv_key=l.inv_key WHERE l.part IN ({q}) AND i.cancelled=0 "
        f"ORDER BY i.inv_date DESC, i.inv_no DESC", tuple(parts))
    best = {}
    for h in hits:
        best.setdefault(h["part"], h)
    vnos = sorted({h["inv_no"] for h in best.values()})
    vmap = {}
    if vnos:
        q2 = ",".join("?" * len(vnos))
        for v in rows(f"SELECT vkey, vno, narration FROM gp_tally_vouchers WHERE vno IN ({q2}) AND vtype LIKE '%SALES%'",
                      tuple(vnos)):
            vmap[v["vno"]] = v
        keys = [v["vkey"] for v in vmap.values()]
        led = {}
        if keys:
            q3 = ",".join("?" * len(keys))
            for x in rows(f"SELECT vkey, ledger FROM gp_tally_vlines WHERE vkey IN ({q3})", tuple(keys)):
                led.setdefault(x["vkey"], []).append(x["ledger"])
        for v in vmap.values():
            v["ledgers"] = led.get(v["vkey"], [])
    for part, h in best.items():
        v = vmap.get(h["inv_no"]) or {}
        gst = None
        for lg in v.get("ledgers", []):
            m = re.search(r"SALES.*?(\d+)\s*%", lg, re.I)
            if m:
                gst = float(m.group(1))
        narr = v.get("narration") or ""
        m = re.search(r"CRATE\s*-\s*(\d+).*?LID\s*-\s*(\d+)", narr, re.I)
        out[part] = dict(item_name=h["item_name"], gst=gst, last_rate=h["rate"], last_inv=h["inv_no"],
                         last_date=h["inv_date"], crate=m.group(1) if m else "", lid=m.group(2) if m else "",
                         carton=bool(re.search(r"CARTON", narr, re.I)))
    return out


def dr_invoiced(dr_nos):
    """DR numbers already written in a Tally invoice's narration -> {dr: inv_no}."""
    found = {}
    for d in dr_nos:
        r = one("SELECT vno FROM gp_tally_vouchers WHERE narration LIKE ? AND vtype LIKE '%SALES%' AND cancelled=0 "
                "ORDER BY vdate DESC LIMIT 1", (f"%DR {d}%",))
        if r:
            found[d] = r["vno"]
    return found


def next_number():
    """The number after the last GST SALES NEW invoice in Tally or in the drafts: '15885/26-27'."""
    best, suffix = 0, ""
    for r in rows("SELECT vno FROM gp_tally_vouchers WHERE vtype=? ORDER BY vdate DESC LIMIT 400",
                  (config()["vtype"],)) + rows("SELECT inv_no vno FROM drinv_drafts WHERE inv_no<>''"):
        m = re.match(r"^(\d+)(/.*)?$", (r["vno"] or "").strip())
        if m and int(m.group(1)) > best:
            best, suffix = int(m.group(1)), m.group(2) or ""
    return f"{best + 1}{suffix}" if best else ""


# ---------------------------------------------------------------- figures
def remarks_for(h, packages, dr_no, bin_type=""):
    n = int(packages or 0) or 1
    if h and h.get("crate"):
        return f"FOR CRATE - {h['crate']} - {n} NOS LID - {h['lid']} - {n} NOS DR {dr_no}"
    if (h and h.get("carton")) or "CARTON" in (bin_type or "").upper():
        return f"FOR CARTON BOX - {n} NOS DR {dr_no}"
    return f"DR {dr_no}"


def compute(d, cfg=None):
    """Totals of one draft (MDU: CGST + SGST, DBR: IGST), rounded to the rupee like Tally."""
    cfg = cfg or config()
    pl = cfg["plants"].get(d.get("plant") or "", {})
    amount = D(d.get("qty")) * D(d.get("rate"))
    amount = amount.quantize(Decimal("0.01"), ROUND_HALF_UP)
    g = D(d.get("gst_rate"))
    cgst = sgst = igst = Decimal(0)
    if pl.get("inter"):
        igst = (amount * g / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    else:
        cgst = (amount * g / 200).quantize(Decimal("0.01"), ROUND_HALF_UP)
        sgst = cgst
    gross = amount + cgst + sgst + igst
    total = gross.quantize(Decimal("1"), ROUND_HALF_UP)
    d.update(amount=float(amount), cgst=float(cgst), sgst=float(sgst), igst=float(igst),
             round_off=float(total - gross), total=float(total), party=pl.get("party", ""))
    return d


def check(d, cfg=None, taken=None):
    """-> list of dict(level='error'|'warn'|'info', text). Errors block Verify and Send."""
    cfg = cfg or config()
    out = []
    add = lambda lv, t: out.append(dict(level=lv, text=t))  # noqa: E731
    if d.get("plant") not in cfg["plants"]:
        add("error", f"PO {d.get('po_no')} is not in the hub's PO data (no plant) - fetch it in Masters > PO master")
    if not d.get("rate"):
        add("error", f"No price for {d.get('part')} on PO {d.get('po_no')} on {d.get('inv_date')}")
    elif d.get("rate_po") is not None and abs((d.get("rate") or 0) - (d.get("rate_po") or 0)) >= 0.005:
        add("warn", f"Rate {d['rate']:.2f} differs from the PO price {d['rate_po']:.2f}")
    lr = d.get("last_rate")
    if d.get("rate") and lr and abs(lr - d["rate"]) >= 0.005:
        add("info", f"Last invoiced in Tally at {lr:.2f} ({d.get('last_inv')}); PO price on this date is "
                    f"{d.get('rate_po') or d['rate']:.2f}")
    if not d.get("item_name"):
        add("error", "Tally stock item not known for this part - type the item name as it is in Tally")
    if not d.get("gst_rate"):
        add("error", "GST % not set")
    no = (d.get("inv_no") or "").strip()
    if not no:
        add("error", "Invoice number not entered")
    else:
        if one("SELECT vno FROM gp_tally_vouchers WHERE vno=? AND vtype LIKE '%SALES%'", (no,)):
            add("error", f"Invoice {no} already exists in Tally")
        if taken and taken.get(no, d.get("id")) != d.get("id"):
            add("error", f"Invoice {no} is used on another draft")
    q, dq = float(d.get("qty") or 0), float(d.get("dr_qty") or 0)
    if q <= 0:
        add("error", "Quantity is 0")
    elif dq and q > dq:
        add("error", f"Quantity {q:g} is more than the DR quantity {dq:g}")
    elif dq and q < dq:
        add("warn", f"Part supply: {q:g} of the DR's {dq:g}")
    pk, pc = float(d.get("packages") or 0), float(d.get("pieces") or 0)
    if not pk:
        add("error", "No of packages not entered")
    if not pc:
        add("error", "No of pieces not entered")
    if pk and pc and abs(pk * pc - q) > 0.001:
        add("warn", f"Packages × pieces = {pk * pc:g}, not the total {q:g}")
    if not re.search(rf"DR\s*{re.escape(d.get('dr_no') or '')}", d.get("remarks") or ""):
        add("warn", "Remarks do not carry the DR number")
    if (d.get("total") or 0) > EWAY_LIMIT:
        add("info", f"Over ₹{EWAY_LIMIT:,}: generate the e-way bill in Tally with the IRN")
    if d.get("_dr_done"):
        add("error", f"DR {d['dr_no']} is already invoiced in Tally ({d['_dr_done']})")
    return out


# ---------------------------------------------------------------- drafts
def _rate(po_no, part, inv_date):
    it = one("SELECT blocks, rate FROM po_items WHERE po_no=? AND part=?", (po_no, part))
    if not it:
        return None
    try:
        r = price_on(json.loads(it["blocks"] or "[]"), inv_date)
    except Exception:  # noqa: BLE001
        r = None
    return r


def _plant(po_no):
    h = one("SELECT plant FROM po_headers WHERE po_no=?", (po_no,))
    p = (h or {}).get("plant") or ""
    if not p:
        p = "MDU" if po_no.startswith("103") else "DBR" if po_no.startswith("121") else ""
    return p


def add_pdf(name, data, inv_date=None):
    """One DR PDF -> drafts (one per part). -> message."""
    lines = dr_pdf.parse_pdf(data)
    if not lines:
        raise ValueError("Not a TAFE Delivery Request (no DR number / part lines found)")
    inv_date = inv_date or date.today().isoformat()
    hist = history([x["part"] for x in lines])
    done = dr_invoiced({x["dr_no"] for x in lines})
    con = get_db()
    made, skipped = 0, 0
    for x in lines:
        if one("SELECT id FROM drinv_drafts WHERE dr_no=? AND part=?", (x["dr_no"], x["part"])):
            skipped += 1
            continue
        h = hist.get(x["part"]) or {}
        rate = _rate(x["order_no"], x["part"], inv_date)
        gst = h.get("gst") or (18.0 if x["part"] in GST18 else 5.0)
        d = dict(dr_no=x["dr_no"], part=x["part"], plant=_plant(x["order_no"]), po_no=x["order_no"],
                 descr=x["descr"], bin=x["bin"], dr_req=x["req"], dr_size=x["size"], dr_qty=x["qty"],
                 item_name=h.get("item_name") or "", gst_rate=gst, inv_no="", inv_date=inv_date, qty=x["qty"],
                 pieces=None, packages=None, kgs="", rate=rate, rate_po=rate,   # entered by the office (packing)
                 remarks=remarks_for(h, x["req"], x["dr_no"], x["bin"]), status="draft", file_name=name,
                 created_by=_user(), created_at=_now(), last_rate=h.get("last_rate"), last_inv=h.get("last_inv"),
                 title=DEFAULT_TITLE)
        compute(d)
        d["_dr_done"] = done.get(x["dr_no"])
        d["issues"] = json.dumps(check(d))
        d.pop("_dr_done")
        cols = list(d)
        con.execute(f"INSERT INTO drinv_drafts({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                    tuple(d[c] for c in cols))
        made += 1
    con.commit()
    dr = lines[0]["dr_no"]
    msg = f"DR {dr}: {made} invoice draft{'s' if made != 1 else ''}"
    if skipped:
        msg += f" ({skipped} already here)"
    if dr in done:
        msg += f" - already invoiced in Tally as {done[dr]}"
    log_event("Uploaded DR", f"{name}: {msg}", [f"DR {x['dr_no']} {x['part']}" for x in lines])
    return dict(message=msg, made=made, skipped=skipped)


def _row(r):
    r = dict(r)
    r["issues"] = json.loads(r.get("issues") or "[]")
    return r


def recheck(ids=None):
    """Re-run the checks on open drafts (numbers taken, invoices pulled from Tally since)."""
    cfg = config()
    where = "WHERE status<>'sent'" + (f" AND id IN ({','.join('?' * len(ids))})" if ids else "")
    ds = rows(f"SELECT * FROM drinv_drafts {where}", tuple(ids or ()))
    taken = {}
    for r in rows("SELECT id, inv_no FROM drinv_drafts WHERE inv_no<>''"):
        taken.setdefault(r["inv_no"].strip(), r["id"])
    dups = {}
    for r in rows("SELECT inv_no, COUNT(*) n FROM drinv_drafts WHERE inv_no<>'' GROUP BY inv_no HAVING n>1"):
        dups[r["inv_no"]] = True
    done = dr_invoiced({d["dr_no"] for d in ds})
    con = get_db()
    for d in ds:
        d["_dr_done"] = done.get(d["dr_no"])
        t = dict(taken)
        if d["inv_no"] in dups:
            t[d["inv_no"]] = -1
        iss = check(d, cfg, t)
        status = d["status"]
        if status == "verified" and any(i["level"] == "error" for i in iss):
            status = "draft"
        con.execute("UPDATE drinv_drafts SET issues=?, status=? WHERE id=?", (json.dumps(iss), status, d["id"]))
    con.commit()


def listing(status=""):
    q = "SELECT * FROM drinv_drafts" + (" WHERE status=?" if status else "") + " ORDER BY status='sent', inv_no='', inv_no, id"
    ds = [_row(r) for r in rows(q, (status,) if status else ())]
    cnt = {r["status"]: r["n"] for r in rows("SELECT status, COUNT(*) n FROM drinv_drafts GROUP BY status")}
    return dict(drafts=ds, counts=cnt, next_no=next_number(), config=public_config(), history=history_log())


def public_config():
    c = config()
    t = c.get("templates") or {}
    return dict(vtype=c["vtype"], company=c["company"], plants=c["plants"],
                learned={p: dict(from_inv=v.get("from_inv"), at=v.get("at"), fields=[f["desc"] for f in v.get("udf", [])],
                                 address=bool(v.get("has_address")))
                         for p, v in t.items()},
                last_learn=c.get("last_learn") or "",
                builtin=[ds for _, ds, _, _ in VOUCHER_UDF + ITEM_UDF])


def update(did, patch):
    d = one("SELECT * FROM drinv_drafts WHERE id=?", (did,))
    if not d:
        raise ValueError("Draft not found")
    if d["status"] == "sent":
        raise ValueError("Already sent to Tally - change it in Tally")
    for k in EDITABLE:
        if k in patch:
            v = patch[k]
            if k in ("qty", "pieces", "packages", "rate", "gst_rate"):
                v = float(v) if str(v).strip() not in ("", "None") else None
            d[k] = v.strip() if isinstance(v, str) else v
    if "inv_date" in patch and "rate" not in patch:
        r = _rate(d["po_no"], d["part"], d["inv_date"])
        d["rate"] = d["rate_po"] = r
    elif "inv_date" in patch:
        d["rate_po"] = _rate(d["po_no"], d["part"], d["inv_date"])
    q = float(d.get("qty") or 0)
    if "packages" in patch and "pieces" not in patch and d.get("packages") and q % float(d["packages"]) == 0:
        d["pieces"] = q / float(d["packages"])
    elif "pieces" in patch and "packages" not in patch and d.get("pieces") and q % float(d["pieces"]) == 0:
        d["packages"] = q / float(d["pieces"])
    elif "qty" in patch and "pieces" not in patch and "packages" not in patch and float(d.get("packages") or 0) == 1:
        d["pieces"] = q
    elif "qty" in patch and "pieces" not in patch and "packages" not in patch and d.get("pieces") \
            and q % float(d["pieces"]) == 0:
        d["packages"] = q / float(d["pieces"])
    if ("packages" in patch or "pieces" in patch or "qty" in patch) and "remarks" not in patch:
        d["remarks"] = re.sub(r"(CRATE - \d+ - |LID - \d+ - |CARTON BOX - )\d+( NOS)",
                              lambda m: f"{m.group(1)}{int(d['packages'] or 0)}{m.group(2)}", d["remarks"] or "")
    compute(d)
    d["status"] = "draft"
    cols = [c for c in d if c != "id"]
    get_db().execute(f"UPDATE drinv_drafts SET {','.join(c + '=?' for c in cols)} WHERE id=?",
                     tuple(d[c] for c in cols) + (did,))
    get_db().commit()
    recheck()
    return _row(one("SELECT * FROM drinv_drafts WHERE id=?", (did,)))


def number_from(start, ids):
    """Give the drafts (in the order given) invoice numbers start, start+1, ... ('15885/26-27')."""
    m = re.match(r"^(\d+)(/.*)?$", (start or "").strip())
    if not m:
        raise ValueError("Start number like 15885/26-27")
    n, suf = int(m.group(1)), m.group(2) or ""
    con = get_db()
    for i, did in enumerate(ids):
        con.execute("UPDATE drinv_drafts SET inv_no=?, status='draft' WHERE id=? AND status<>'sent'", (f"{n + i}{suf}", did))
    con.commit()
    log_event("Numbered", f"{len(ids)} invoice(s) from {n}{suf}")
    recheck()


def verify(ids, on=True, force=False):
    """on: draft -> verified (blocked by errors). off: back to draft; force also takes back an invoice marked
    'sent' (after it was deleted in Tally, to send it again)."""
    recheck(ids)
    con = get_db()
    bad, done = [], []
    for d in rows(f"SELECT * FROM drinv_drafts WHERE id IN ({','.join('?' * len(ids))})", tuple(ids)):
        if d["status"] == "sent" and not (force and not on):
            continue
        if on and any(i["level"] == "error" for i in json.loads(d["issues"] or "[]")):
            bad.append(d["inv_no"] or f"DR {d['dr_no']}")
            continue
        con.execute("UPDATE drinv_drafts SET status=?, verified_by=?, verified_at=?, tally_msg=? WHERE id=?",
                    ("verified" if on else "draft", _user() if on else None, _now() if on else None,
                     None if d["status"] == "sent" else d.get("tally_msg"), d["id"]))
        done.append(d["inv_no"] or f"DR {d['dr_no']}")
    con.commit()
    if done:
        log_event("Verified" if on else ("Back to draft (was in Tally)" if force else "Back to draft"),
                  f"{len(done)} invoice(s)", done)
    return bad


def remove(ids):
    gone = [d["inv_no"] or f"DR {d['dr_no']}" for d in rows(
        f"SELECT inv_no, dr_no FROM drinv_drafts WHERE status<>'sent' AND id IN ({','.join('?' * len(ids))})", tuple(ids))]
    get_db().execute(f"DELETE FROM drinv_drafts WHERE status<>'sent' AND id IN ({','.join('?' * len(ids))})", tuple(ids))
    get_db().commit()
    if gone:
        log_event("Deleted drafts", f"{len(gone)} draft(s)", gone)


# ---------------------------------------------------------------- Tally
def _x(s):
    return html.escape(str(s if s is not None else ""), quote=False)


def _tdate(iso):
    return iso.replace("-", "")


def _num(v):
    v = float(v or 0)
    return f"{v:.0f}" if v == int(v) else f"{v:g}"


# what a real TAFE invoice carries about the buyer / consignee (copied from it when the format is learned)
PARTY_PREFIX = ("PARTY", "CONSIGNEE", "BASICBUYER", "BUYER", "BASICBASEPARTY")
PARTY_TAGS = ("STATENAME", "COUNTRYOFRESIDENCE", "PLACEOFSUPPLY", "GSTREGISTRATIONTYPE", "VCHGSTCLASS")
SKIP_TAGS = {"PARTYLEDGERNAME", "BASICBUYERNAME"}          # written by the hub itself


def _role(desc):
    k = re.sub(r"[^A-Z]", "", (desc or "").upper())
    if k.startswith("PO") and ("NUMBER" in k or k.endswith("NO")):
        return "po"
    if "PICES" in k or "PIECES" in k:
        return "pieces"
    if "PACKAGE" in k or "PACKEGE" in k:
        return "packages"
    if "TOTALNOS" in k or k == "NOS":
        return "qty"
    if "KG" in k:
        return "kgs"
    if "TITLE" in k:
        return "title"
    return "fixed"


def _norm(s):
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip().lower()


def learn(text, company=""):
    """A Tally Day Book answer -> per plant, what its newest GST SALES NEW invoice to TAFE carries:
    the user-defined fields (PO NUMBER, Title, NO OF PICES, ...), buyer / consignee details and address,
    unit and godown. When nothing matches, the answer is described (what Tally sent) so it can be put right."""
    cfg = config()
    err = re.search(r"<LINEERROR>(.*?)</LINEERROR>", text or "", re.S)
    if err:
        msg = f"Tally said: {html.unescape(err.group(1)).strip()}"
        save_config(dict(last_learn=msg))
        return dict(ok=False, learned=[], message=msg)
    party_plant = {_norm(v["party"]): p for p, v in cfg["plants"].items()}
    vt_want = _norm(cfg["vtype"])
    learned, types, parties, n = {}, {}, {}, 0
    for m in re.finditer(r"<VOUCHER\b([^>]*)>(.*?)</VOUCHER>", text or "", re.S):
        n += 1
        attrs, v = m.group(1), m.group(2)
        vt = re.search(r"<VOUCHERTYPENAME>(.*?)</VOUCHERTYPENAME>", v)
        vt = _norm(vt.group(1)) if vt else _norm((re.search(r'VCHTYPE="([^"]*)"', attrs) or [None, ""])[1])
        types[vt] = types.get(vt, 0) + 1
        pl = None
        for tag in ("PARTYLEDGERNAME", "PARTYNAME", "BASICBUYERNAME"):
            mm = re.search(rf"<{tag}>(.*?)</{tag}>", v)
            if mm and _norm(mm.group(1)) in party_plant:
                pl = party_plant[_norm(mm.group(1))]
                break
            if mm and tag == "PARTYLEDGERNAME":
                parties[_norm(mm.group(1))] = 1
        if vt != vt_want or not pl or pl in learned:
            continue
        head = re.sub(r"<(ALLINVENTORYENTRIES|LEDGERENTRIES|ALLLEDGERENTRIES|INVENTORYENTRIES)\.LIST>.*?"
                      r"</\1\.LIST>", "", v, flags=re.S)
        udf = []
        for u in re.finditer(r"<(UDF:[A-Za-z0-9_]+)\.LIST([^>]*)>\s*<\1([^>]*)>(.*?)</\1>\s*</\1\.LIST>", head, re.S):
            desc = re.search(r'DESC="`?([^"`]*)`?"', u.group(2) + u.group(3))
            desc = desc.group(1) if desc else u.group(1)[4:]
            udf.append(dict(tag=u.group(1), list_attrs=u.group(2), attrs=u.group(3), desc=desc,
                            sample=html.unescape(u.group(4)), role=_role(desc)))
        tags = {}
        for t, val in re.findall(r"<([A-Z][A-Z0-9]*)>([^<]*)</\1>", head):
            if not val.strip() or t in SKIP_TAGS:
                continue
            if t.startswith(PARTY_PREFIX) or t in PARTY_TAGS:
                tags.setdefault(t, f"<{t}>{val}</{t}>")
        has_addr = False
        for mm in re.finditer(r"<([A-Z]*ADDRESS)\.LIST\b[^>]*>(.*?)</\1\.LIST>", head, re.S):
            if "EWAY" in mm.group(1) or not re.sub(r"<[^>]+>|\s", "", mm.group(2)):
                continue
            tags.setdefault(mm.group(1) + ".LIST", mm.group(0))
            has_addr = True
        unit = re.search(r"<BILLEDQTY>\s*[\d.]+\s*([A-Za-z.]+)\s*</BILLEDQTY>", v)
        god = re.search(r"<GODOWNNAME>(.*?)</GODOWNNAME>", v)
        od = re.search(r"<BASICORDERDATE>(\d{8})</BASICORDERDATE>", v)
        po = re.search(r"<BASICPURCHASEORDERNO>(.*?)</BASICPURCHASEORDERNO>", v)
        no = re.search(r"<VOUCHERNUMBER>(.*?)</VOUCHERNUMBER>", v)
        learned[pl] = dict(udf=udf, tags=tags, has_address=has_addr, unit=unit.group(1) if unit else cfg["unit"],
                           godown=html.unescape(god.group(1)) if god else "",
                           order_date=od.group(1) if od else "", order_po=po.group(1) if po else "",
                           order_list=bool(re.search(r"<INVOICEORDERLIST\.LIST>", v)),
                           from_inv=no.group(1) if no else "", at=_now())
    if not learned:
        top = ", ".join(f"{k or '?'} ({c})" for k, c in sorted(types.items(), key=lambda x: -x[1])[:6])
        msg = (f"No {cfg['vtype']} invoice to TAFE in Tally's answer{f' (company {company})' if company else ''}: "
               f"{n} voucher(s), {len(text or '') // 1024} KB" + (f"; types {top}" if n else "") +
               (f"; parties e.g. {', '.join(list(parties)[:4])}" if parties else "") +
               ("" if n else f"; Tally sent: {re.sub(r'<[^>]+>', ' ', (text or '')[:300]).strip()[:200] or 'nothing'}"))
        save_config(dict(last_learn=msg))
        return dict(ok=False, learned=[], message=msg)
    t = dict(cfg.get("templates") or {})
    t.update(learned)
    msg = "Learned from " + ", ".join(
        f"{p} invoice {v['from_inv']} (fields: {', '.join(u['desc'] for u in v['udf']) or 'none'}"
        f"{', address' if v['has_address'] else ''})" for p, v in sorted(learned.items()))
    save_config(dict(templates=t, last_learn=msg))
    log_event("Learned Tally format", msg)
    return dict(ok=True, learned=sorted(learned), message=msg)


def learn_request():
    """Day Book requests: per plant the last 3 days Tally had GST SALES NEW invoices to it (one request a day,
    small enough for the website), newest first. The browser stops once every plant is learned."""
    from ..grin.services.tally import daybook_request
    cfg = config()
    days = []
    for p in cfg["plants"].values():
        for r in rows("SELECT DISTINCT vdate d FROM gp_tally_vouchers WHERE vtype=? AND party=? AND cancelled=0 "
                      "ORDER BY vdate DESC LIMIT 3", (cfg["vtype"], p["party"])):
            if r["d"] and r["d"] not in days:
                days.append(r["d"])
    if not days:
        days = [date.today().isoformat()]
    days.sort(reverse=True)
    return [daybook_request(cfg["company"], date.fromisoformat(d), date.fromisoformat(d)) for d in days[:6]]


def _party_xml(pl, tp=None):
    """Buyer and consignee exactly as Tally fills them from the party ledger (copied from real invoices)."""
    name, state, pin, gstin = pl["party"], pl.get("state"), pl.get("pincode"), pl.get("gstin")
    vals = [("GSTREGISTRATIONTYPE", "Regular"), ("VATDEALERTYPE", "Regular"), ("STATENAME", state),
            ("COUNTRYOFRESIDENCE", "India"), ("PARTYGSTIN", gstin), ("PLACEOFSUPPLY", state), ("PARTYNAME", name),
            ("PARTYMAILINGNAME", name), ("PARTYPINCODE", pin), ("BILLTOPLACE", pl.get("place")),
            ("SHIPTOPLACE", pl.get("place")), ("CONSIGNEEGSTIN", gstin), ("CONSIGNEEMAILINGNAME", name),
            ("CONSIGNEEPINCODE", pin), ("CONSIGNEESTATENAME", state), ("CONSIGNEECOUNTRYNAME", "India"),
            ("BASICBASEPARTYNAME", name), ("CONSIGNEECSTNUMBER", pl.get("cst")), ("BUYERSCSTNUMBER", pl.get("cst")),
            ("TRADERCONSVATTINNO", pl.get("tin")), ("BASICBUYERSSALESTAXNO", pl.get("tin"))]
    out = [f"<{t}>{_x(v)}</{t}>" for t, v in vals if v]
    if pl.get("address"):
        out.append('<ADDRESS.LIST TYPE="String">' + "".join(f"<ADDRESS>{_x(a)}</ADDRESS>" for a in pl["address"])
                   + "</ADDRESS.LIST>")
        out.append('<BASICBUYERADDRESS.LIST TYPE="String">' +
                   "".join(f"<BASICBUYERADDRESS>{_x(a)}</BASICBUYERADDRESS>" for a in pl["address"]) +
                   "</BASICBUYERADDRESS.LIST>")
    return "\n".join(out)


def _ledger(name, amount, party=False):
    """Party / tax line. Tally: debit = negative amount + deemed positive Yes."""
    dp = "Yes" if amount < 0 else "No"
    extra = "<ISPARTYLEDGER>Yes</ISPARTYLEDGER>" if party else "<ISPARTYLEDGER>No</ISPARTYLEDGER>"
    rt = "" if party else "<ROUNDTYPE>Normal Rounding</ROUNDTYPE>"
    return (f"<LEDGERENTRIES.LIST>{rt}<LEDGERNAME>{_x(name)}</LEDGERNAME><ISDEEMEDPOSITIVE>{dp}</ISDEEMEDPOSITIVE>"
            f"{extra}<ISLASTDEEMEDPOSITIVE>{dp}</ISLASTDEEMEDPOSITIVE><AMOUNT>{amount:.2f}</AMOUNT>")


def _round_off(name, ro):
    """Round Off exactly like the office's invoices: always deemed positive No, the amount with its sign
    (-0.06 when the bill is rounded down, 0.42 when rounded up), Normal Rounding to 1 rupee. Sending it as a
    debit (Yes / -0.44) made Tally's invoice show +0.44 and a total 0.88 too high."""
    return (f"<LEDGERENTRIES.LIST><ROUNDTYPE>Normal Rounding</ROUNDTYPE><LEDGERNAME>{_x(name)}</LEDGERNAME>"
            f"<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><ISPARTYLEDGER>No</ISPARTYLEDGER>"
            f"<ISLASTDEEMEDPOSITIVE>No</ISLASTDEEMEDPOSITIVE><ROUNDLIMIT> 1</ROUNDLIMIT>"
            f"<AMOUNT>{ro:.2f}</AMOUNT><VATEXPAMOUNT>{ro:.2f}</VATEXPAMOUNT></LEDGERENTRIES.LIST>\n")


def _udf(tag, desc, index, val):
    return (f'<{tag}.LIST DESC="`{desc}`" ISLIST="YES" TYPE="String" INDEX="{index}">'
            f'<{tag} DESC="`{desc}`">{_x(val)}</{tag}></{tag}.LIST>\n')


def tafe_key(po_no, inv_no, inv_date):
    """TAFE Key ID as the office's TDL writes it: "DS1615$1030000676$156212627$14112026"."""
    y, m, dd = inv_date.split("-")
    return f'"{VENDOR_CODE}${po_no}${re.sub(r"[^0-9]", "", inv_no or "")}${dd}{m}{y}"'


def voucher_xml(d, cfg=None):
    cfg = cfg or config()
    pl = cfg["plants"][d["plant"]]
    unit = cfg["unit"]
    godown = cfg.get("godown") or ""
    sales = pl["sales"].get(_num(d["gst_rate"])) or pl["sales"].get(str(int(d["gst_rate"])))
    if not sales:
        raise ValueError(f"No sales ledger for GST {d['gst_rate']}% ({d['plant']})")
    amt, total = d["amount"], d["total"]
    qty = f" {_num(d['qty'])} {unit}"
    vals = dict(po=d["po_no"], pieces=_num(d["pieces"]), packages=_num(d["packages"]), qty=_num(d["qty"]),
                title=d.get("title") or DEFAULT_TITLE, durgaparty=pl.get("durgaparty") or "",
                appid=tafe_key(d["po_no"], d["inv_no"], d["inv_date"]),
                rate=f"{d['rate']:.2f}", part=d["part"])
    udf = "".join(_udf(t, ds, ix, vals[r]) for t, ds, ix, r in VOUCHER_UDF if vals.get(r) not in (None, ""))
    item_udf = "".join(_udf(t, ds, ix, vals[r]) for t, ds, ix, r in ITEM_UDF if vals.get(r) not in (None, ""))
    od = PO_ORDER_DATE.get(d["po_no"]) or ""
    if not od:
        h = one("SELECT po_date FROM po_headers WHERE po_no=?", (d["po_no"],))
        mm = re.match(r"(\d\d)\.(\d\d)\.(\d{4})", (h or {}).get("po_date") or "")
        od = f"{mm.group(3)}{mm.group(2)}{mm.group(1)}" if mm else ""
    order = (f"<INVOICEORDERLIST.LIST>{f'<BASICORDERDATE>{od}</BASICORDERDATE>' if od else ''}"
             f"<BASICPURCHASEORDERNO>{_x(d['po_no'])}</BASICPURCHASEORDERNO></INVOICEORDERLIST.LIST>")
    # no <ORDERNO> on the item line: that links the item to a Tally SALES ORDER (see the 610.83 elbow, Nov 2026)
    batch = (f"<BATCHALLOCATIONS.LIST>{f'<GODOWNNAME>{_x(godown)}</GODOWNNAME>' if godown else ''}"
             f"<BATCHNAME>Primary Batch</BATCHNAME>"
             f"{f'<DESTINATIONGODOWNNAME>{_x(godown)}</DESTINATIONGODOWNNAME>' if godown else ''}"
             f"<AMOUNT>{amt:.2f}</AMOUNT><ACTUALQTY>{qty}</ACTUALQTY><BILLEDQTY>{qty}</BILLEDQTY>"
             f"<BATCHRATE>{d['rate']:.2f}/{unit}</BATCHRATE></BATCHALLOCATIONS.LIST>")
    taxes = ""
    for led, v in ((cfg["cgst"], d["cgst"]), (cfg["sgst"], d["sgst"]), (cfg["igst"], d["igst"])):
        if v:
            taxes += _ledger(led, v) + f"<VATEXPAMOUNT>{v:.2f}</VATEXPAMOUNT></LEDGERENTRIES.LIST>\n"
    ro = d["round_off"] or 0
    if abs(ro) >= 0.005:
        taxes += _round_off(cfg["round_off"], ro)
    party_led = _ledger(pl["party"], -total, party=True)
    return f"""<VOUCHER VCHTYPE="{_x(cfg['vtype'])}" ACTION="Create" OBJVIEW="Invoice Voucher View">
<DATE>{_tdate(d['inv_date'])}</DATE><EFFECTIVEDATE>{_tdate(d['inv_date'])}</EFFECTIVEDATE>
<VOUCHERTYPENAME>{_x(cfg['vtype'])}</VOUCHERTYPENAME><VOUCHERNUMBER>{_x(d['inv_no'])}</VOUCHERNUMBER>
<PARTYLEDGERNAME>{_x(pl['party'])}</PARTYLEDGERNAME><BASICBUYERNAME>{_x(pl['party'])}</BASICBUYERNAME>
{_party_xml(pl)}
<NARRATION>{_x(d['remarks'])}</NARRATION><ISINVOICE>Yes</ISINVOICE>
<PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW><VCHENTRYMODE>Item Invoice</VCHENTRYMODE>
{order}
{udf}{party_led}
<BILLALLOCATIONS.LIST><NAME>{_x(d['inv_no'])}</NAME><BILLTYPE>New Ref</BILLTYPE><AMOUNT>{-total:.2f}</AMOUNT></BILLALLOCATIONS.LIST>
</LEDGERENTRIES.LIST>
<ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>{_x(d['item_name'])}</STOCKITEMNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
<ISLASTDEEMEDPOSITIVE>No</ISLASTDEEMEDPOSITIVE>
<RATE>{d['rate']:.2f}/{unit}</RATE><AMOUNT>{amt:.2f}</AMOUNT><ACTUALQTY>{qty}</ACTUALQTY><BILLEDQTY>{qty}</BILLEDQTY>
{item_udf}{batch}
<ACCOUNTINGALLOCATIONS.LIST><LEDGERNAME>{_x(sales)}</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><ISLASTDEEMEDPOSITIVE>No</ISLASTDEEMEDPOSITIVE><AMOUNT>{amt:.2f}</AMOUNT></ACCOUNTINGALLOCATIONS.LIST>
</ALLINVENTORYENTRIES.LIST>
{taxes}</VOUCHER>"""


def import_xml(d, cfg=None):
    cfg = cfg or config()
    comp = f"<SVCURRENTCOMPANY>{_x(cfg['company'])}</SVCURRENTCOMPANY>" if cfg.get("company") else ""
    return (f"<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA><REQUESTDESC>"
            f"<REPORTNAME>Vouchers</REPORTNAME><STATICVARIABLES>{comp}</STATICVARIABLES></REQUESTDESC><REQUESTDATA>"
            f'<TALLYMESSAGE xmlns:UDF="TallyUDF">\n{voucher_xml(d, cfg)}\n</TALLYMESSAGE></REQUESTDATA></IMPORTDATA>'
            f"</BODY></ENVELOPE>")


def send_plan(ids):
    """Verified drafts -> [dict(id, inv_no, xml)] to post to Tally one by one. no_fields: plants whose invoice
    format (NO OF PICES, NO OF PACKAGES, TOTAL NOS ... fields) is not learned - those would reach Tally empty."""
    cfg = config()
    recheck(ids)
    out, skipped, plants = [], [], set()
    for d in rows(f"SELECT * FROM drinv_drafts WHERE id IN ({','.join('?' * len(ids))}) ORDER BY inv_no", tuple(ids)):
        if d["status"] != "verified":
            skipped.append(d["inv_no"] or f"DR {d['dr_no']}")
            continue
        plants.add(d["plant"])
        out.append(dict(id=d["id"], inv_no=d["inv_no"], xml=import_xml(d, cfg)))
    # the invoice format (TDL fields, party details, Round Off) is built in from Tally's real invoices
    return dict(items=out, skipped=skipped, need_learn=[], no_fields=[])


def tally_result(did, text):
    """Tally's answer to one import -> sent (CREATED 1) or the error kept on the draft."""
    def n(tag):
        m = re.search(rf"<{tag}>\s*(\d+)\s*</{tag}>", text or "")
        return int(m.group(1)) if m else 0
    errs = re.findall(r"<LINEERROR>(.*?)</LINEERROR>", text or "", re.S)
    created, altered = n("CREATED"), n("ALTERED")
    con = get_db()
    d = one("SELECT inv_no FROM drinv_drafts WHERE id=?", (did,)) or {}
    if (created or altered) and not n("ERRORS"):
        con.execute("UPDATE drinv_drafts SET status='sent', sent_by=?, sent_at=?, tally_msg=? WHERE id=?",
                    (_user(), _now(), "Created in Tally", did))
        con.commit()
        log_event("Sent to Tally", d.get("inv_no") or "", [d.get("inv_no")])
        return dict(ok=True)
    msg = "; ".join(html.unescape(e).strip() for e in errs) or (text or "").strip()[:300] or "Tally gave no answer"
    con.execute("UPDATE drinv_drafts SET tally_msg=? WHERE id=?", (msg, did))
    con.commit()
    log_event("Tally refused", f"{d.get('inv_no')}: {msg}", [d.get("inv_no")])
    return dict(ok=False, error=msg)


# ---------------------------------------------------------------- "Read Tally structure"
# Reads from Tally, through the bridge, exactly how it keeps a TAFE invoice: chosen invoices in full (Day Book,
# every field incl. the TDL fields Title / NO OF PICES ..., buyer / consignee address, Round Off line) and the
# party, Round Off and sales ledgers. Kept raw in drinv_samples (and data/tally_samples on the PC hub) so the
# hub's invoices can be made to match Tally exactly.
SAMPLE_MAX = 400_000


def structure_defaults():
    """Suggested invoices: the newest invoice typed in Tally for MDU and for DBR, and the newest sent by the hub."""
    cfg = config()
    hub_nos = {r["inv_no"] for r in rows("SELECT inv_no FROM drinv_drafts WHERE status='sent'")}
    out = []
    for p in cfg["plants"].values():
        for r in rows("SELECT vno FROM gp_tally_vouchers WHERE vtype=? AND party=? AND cancelled=0 "
                      "ORDER BY vdate DESC, vno DESC LIMIT 30", (cfg["vtype"], p["party"])):
            if r["vno"] not in hub_nos:
                out.append(r["vno"])
                break
    r = one("SELECT inv_no FROM drinv_drafts WHERE status='sent' ORDER BY sent_at DESC LIMIT 1")
    if r:
        out.append(r["inv_no"])
    return out


def _ledger_request(company, name):
    comp = f"<SVCURRENTCOMPANY>{_x(company)}</SVCURRENTCOMPANY>" if company else ""
    q = name.replace('"', "")
    return f"""<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE>
<ID>SDEWHubOneLedger</ID></HEADER><BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>{comp}
</STATICVARIABLES><TDL><TDLMESSAGE><COLLECTION NAME="SDEWHubOneLedger" ISMODIFY="No"><TYPE>Ledger</TYPE>
<NATIVEMETHOD>*</NATIVEMETHOD><FETCH>*, Address.*, LedMailingDetails.*, LedGSTRegDetails.*, LanguageName.*</FETCH>
<FILTER>SDEWHubThisLedger</FILTER></COLLECTION>
<SYSTEM TYPE="Formulae" NAME="SDEWHubThisLedger">$Name = "{_x(q)}"</SYSTEM></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"""


def _voucher_request(company, vno):
    comp = f"<SVCURRENTCOMPANY>{_x(company)}</SVCURRENTCOMPANY>" if company else ""
    q = vno.replace('"', "")
    return f"""<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE>
<ID>SDEWHubOneVoucher</ID></HEADER><BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>{comp}
<SVFROMDATE TYPE="Date">01-Apr-2026</SVFROMDATE><SVTODATE TYPE="Date">31-Mar-2027</SVTODATE>
</STATICVARIABLES><TDL><TDLMESSAGE><COLLECTION NAME="SDEWHubOneVoucher" ISMODIFY="No"><TYPE>Voucher</TYPE>
<NATIVEMETHOD>*</NATIVEMETHOD><FETCH>*, AllInventoryEntries.*, LedgerEntries.*, AllLedgerEntries.*, InvoiceOrderList.*</FETCH>
<FILTER>SDEWHubThisVoucher</FILTER></COLLECTION>
<SYSTEM TYPE="Formulae" NAME="SDEWHubThisVoucher">$VoucherNumber = "{_x(q)}"</SYSTEM></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"""


def structure_plan(nos):
    """-> requests for the browser (or the PC hub) to send to Tally: Day Book of each invoice's date, the same
    invoice as a collection, and the ledgers. Unknown invoice numbers are reported."""
    from ..grin.services.tally import daybook_request
    cfg = config()
    nos = [n.strip() for n in nos if n and n.strip()]
    reqs, unknown, dates = [], [], {}
    for n in nos:
        r = one("SELECT vdate FROM gp_tally_vouchers WHERE vno=? ORDER BY vdate DESC LIMIT 1", (n,)) or \
            one("SELECT inv_date vdate FROM drinv_drafts WHERE inv_no=?", (n,))
        if not r or not r["vdate"]:
            unknown.append(n)
            continue
        dates.setdefault(r["vdate"], []).append(n)
        reqs.append(dict(kind="voucher", ref=n, want=[n], xml=_voucher_request(cfg["company"], n)))
    for d, want in sorted(dates.items()):
        dd = date.fromisoformat(d)
        reqs.append(dict(kind="daybook", ref=d, want=want, xml=daybook_request(cfg["company"], dd, dd)))
    names = [p["party"] for p in cfg["plants"].values()] + [cfg["round_off"]] + \
            sorted({v for p in cfg["plants"].values() for v in p["sales"].values()})
    for nm in names:
        reqs.append(dict(kind="ledger", ref=nm, want=[], xml=_ledger_request(cfg["company"], nm)))
    return dict(requests=reqs, unknown=unknown)


def _summary(v):
    """What matters in one voucher: TDL (UDF) fields, address / party tags, the ledger lines as Tally wrote them."""
    head = re.sub(r"<(ALLINVENTORYENTRIES|INVENTORYENTRIES)\.LIST>.*?</\1\.LIST>", "", v, flags=re.S)
    udf = sorted(set(re.findall(r"<(UDF:[A-Za-z0-9_]+)\.LIST([^>]*)>", head)))
    addr = [re.sub(r"\s+", " ", m.group(0))[:300] for m in re.finditer(r"<([A-Z]*ADDRESS)\.LIST\b[^>]*>(.*?)</\1\.LIST>", head, re.S)
            if re.sub(r"<[^>]+>|\s", "", m.group(2))]
    led = []
    for m in re.finditer(r"<(LEDGERENTRIES|ALLLEDGERENTRIES)\.LIST>(.*?)</\1\.LIST>", v, re.S):
        b = m.group(2)
        f = dict(re.findall(r"<(LEDGERNAME|ISDEEMEDPOSITIVE|ISLASTDEEMEDPOSITIVE|ISPARTYLEDGER|AMOUNT|ROUNDTYPE|"
                            r"METHODTYPE|ROUNDLIMIT|VATEXPAMOUNT)>([^<]*)<", b))
        led.append(f)
    return dict(udf=[dict(tag=t, attrs=a.strip()) for t, a in udf], address=addr, ledgers=led,
                tags=sorted(set(t for t, val in re.findall(r"<([A-Z][A-Z0-9]*)>([^<]+)</\1>", head)
                                if val.strip() and t.startswith(("PARTY", "CONSIGNEE", "BASICBUYER", "BUYER", "STATE",
                                                                  "PLACEOFSUPPLY", "GSTREG", "COUNTRY")))))


def structure_save(kind, ref, text, want=None):
    """One Tally answer -> drinv_samples rows (the wanted invoices only, for a Day Book). -> short report."""
    from .. import config as hubconfig
    want = set(want or [])
    err = re.search(r"<LINEERROR>(.*?)</LINEERROR>", text or "", re.S)
    saved = []
    con = get_db()

    def keep(k, r, body, summ):
        body = body[:SAMPLE_MAX]
        con.execute("INSERT INTO drinv_samples(at, user, kind, ref, summary, text) VALUES(?,?,?,?,?,?)",
                    (_now(), _user(), k, r, json.dumps(summ), body))
        saved.append(dict(kind=k, ref=r, size=len(body), summary=summ))
        if not hubconfig.ON_VERCEL:        # the PC hub: also as files, data/tally_samples/
            try:
                import os
                d = os.path.join(hubconfig.DATA_DIR, "tally_samples")
                os.makedirs(d, exist_ok=True)
                fn = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{datetime.now():%Y%m%d_%H%M%S}_{k}_{r}") + ".xml"
                with open(os.path.join(d, fn), "w", encoding="utf-8") as fh:
                    fh.write(body)
            except Exception:  # noqa: BLE001
                pass

    if err or "<ENVELOPE" not in (text or "").upper():
        keep(kind + "-error", ref, text or "", dict(error=(html.unescape(err.group(1)) if err else (text or "")[:300])))
    elif kind in ("voucher", "daybook"):
        found = 0
        for m in re.finditer(r"<VOUCHER\b[^>]*>.*?</VOUCHER>", text, re.S):
            v = m.group(0)
            no = re.search(r"<VOUCHERNUMBER>(.*?)</VOUCHERNUMBER>", v)
            no = html.unescape(no.group(1)).strip() if no else ""
            if want and no not in want:
                continue
            found += 1
            keep(kind, no or ref, v, _summary(v))
        if not found:
            keep(kind + "-empty", ref, text[:SAMPLE_MAX], dict(error=f"None of {', '.join(sorted(want))} in Tally's answer",
                                                            vouchers=len(re.findall(r"<VOUCHER\b", text))))
    else:
        keep(kind, ref, text, dict(size=len(text)))
    con.commit()
    out = dict(saved=[dict(kind=x["kind"], ref=x["ref"], size=x["size"], summary=x["summary"]) for x in saved])
    if kind == "daybook" and not err:
        hub_nos = {r["inv_no"] for r in rows("SELECT inv_no FROM drinv_drafts WHERE status='sent'")}
        office = [x for x in saved if x["kind"] == "daybook" and x["ref"] not in hub_nos]
        if office:                       # an invoice typed in Tally: learn the format from it too
            out["learn"] = learn(text, "")
    return out


def samples(limit=60):
    return [dict(r, summary=json.loads(r["summary"] or "{}")) for r in
            rows("SELECT id, at, user, kind, ref, summary, LENGTH(text) size FROM drinv_samples ORDER BY id DESC LIMIT ?",
                 (limit,))]


def samples_text(ids=None):
    q = "SELECT * FROM drinv_samples" + (f" WHERE id IN ({','.join('?' * len(ids))})" if ids else "") + " ORDER BY id"
    parts = []
    for r in rows(q, tuple(ids or ())):
        parts.append(f"<!-- ===== #{r['id']} {r['kind']} {r['ref']} read {r['at']} by {r['user']} ===== -->\n{r['text']}\n")
    return "".join(parts)
