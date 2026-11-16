"""Reading the uploads and the two checks (see __init__.py)."""
import html as _html
import io
import json
import os
import re
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta

from ..db import get_db, one, rows
from ..supp.services import po_parser

KINDS = ("excel", "new", "old")


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _num(v):
    try:
        return round(float(str(v).replace(",", "").strip()), 4)
    except (TypeError, ValueError):
        return None


def _iso(v):
    """dd.mm.yyyy / dd/mm/yyyy / dd-mm-yyyy / a date -> yyyy-mm-dd, or ''."""
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    m = re.match(r"\s*(\d{1,2})[./-](\d{1,2})[./-](\d{4})", str(v or ""))
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else ""


def _dmy(iso):
    return f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}"


def _block_rate(b):
    """A PO .htm price block: Gross Price is the basic price (TAFE's Excel compares basic prices).
    Blocks without the condition names (older uploads) give their total."""
    c = b.get("conds") or {}
    if "gross" in c:
        return round(c["gross"], 2)
    return round(sum(c.values()), 2)


def rate_on(blocks, iso_day):
    for b in blocks:
        if _ymd(b["frm"]) <= iso_day <= _ymd(b["to"]):
            return _block_rate(b)
    return None


def _ymd(dmy):
    return f"{dmy[6:10]}-{dmy[3:5]}-{dmy[0:2]}"


# ---------------------------------------------------------------- reading the uploads
def _html_rows(text):
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
        cells = [_html.unescape(re.sub(r"<[^>]+>", "", c)).replace("\xa0", " ").strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
        if cells:
            out.append(cells)
    return out


def _sheet_rows(name, data):
    """All rows of an Excel file: real .xls/.xlsx, or the HTML table TAFE Channel saves as .xls."""
    if data[:200].lstrip().lower().startswith((b"<!doctype", b"<html", b"<table")):
        return _html_rows(data.decode("utf-8", errors="ignore"))
    from ..supp.services.readers import sheets
    suffix = os.path.splitext(name)[1] or ".xls"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
        fh.write(data)
        path = fh.name
    try:
        out = []
        for _, it in sheets(path):
            out += [["" if v is None else v for v in r] for r in it]
        return out
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def read_excel(name, data):
    """TAFE's price-change Excel -> parts [{part, descr, existing, revised, effective, net}]. Each part has
    material rows and one 'ZZASSY' row; the ZZASSY row carries the component's Existing / Revised Basic price."""
    rows_ = _sheet_rows(name, data)
    head = None
    for i, r in enumerate(rows_):
        names = [str(c).strip().lower() for c in r]
        if any("part no" in c for c in names) and any("revised" in c and "basic" in c for c in names):
            head = i
            break
    if head is None:
        raise ValueError(f"{name}: no 'TAFE Part No' / 'Revised Basic price' columns - is this TAFE's price-change Excel?")
    h = [re.sub(r"\s+", " ", str(c)).strip().lower() for c in rows_[head]]

    def col(*words, last=False):
        idx = [j for j, c in enumerate(h) if all(w in c for w in words)]
        return (idx[-1] if last else idx[0]) if idx else None
    c_part, c_desc, c_grade = col("part no"), col("description"), col("grade")
    c_old, c_new, c_eff, c_net = col("existing", "basic"), col("revised", "basic"), col("effective"), col("net")
    parts = {}
    for r in rows_[head + 1:]:
        g = lambda c, r=r: (r[c] if c is not None and c < len(r) else "")  # noqa: E731
        part = re.sub(r"\s+", "", str(g(c_part))).upper()
        if not part:
            continue
        grade = str(g(c_grade)).strip().upper()
        new = _num(g(c_new))
        is_assy = grade == "ZZASSY" or (c_grade is None and new)
        if not is_assy and not (new and part not in parts):
            continue
        parts[part] = dict(part=part, descr=str(g(c_desc)).strip(), existing=_num(g(c_old)), revised=new,
                           effective=_iso(g(c_eff)), net=_num(g(c_net)))
    m = re.search(r"DS\d+_(\d{6,})", name)
    return dict(doc=m.group(1) if m else "", parts=list(parts.values()))


def read_po(name, data):
    text = data.decode("utf-8", errors="ignore")
    if not po_parser.looks_like_po(text):
        raise ValueError(f"{name}: this is not a TAFE PO saved as .htm")
    po = po_parser.parse(text)
    if not po["po_no"]:
        raise ValueError(f"{name}: PO number not found")
    return dict(po_no=po["po_no"], po_date=po["po_date"], valid_till=po["valid_till"], plant=po["plant_hint"],
                items=[dict(item=it["item"], part=it["part"], issue=it.get("iss", ""), descr=it["descr"], uom=it["uom"],
                            blocks=it["blocks"]) for it in po["items"]],
                warnings=po["warnings"][:10])


def add_file(kind, name, data):
    if kind not in KINDS:
        raise ValueError("kind must be excel, new or old")
    parsed = read_excel(name, data) if kind == "excel" else read_po(name, data)
    con = get_db()
    po_no = parsed.get("po_no", "")
    if kind in ("new", "old"):        # one file per PO and kind: a later upload replaces the earlier one
        con.execute("DELETE FROM pc_files WHERE kind=? AND po_no=?", (kind, po_no))
    else:
        con.execute("DELETE FROM pc_files WHERE kind=? AND name=?", (kind, name))
    con.execute("INSERT INTO pc_files(kind, name, po_no, uploaded_at, data) VALUES(?,?,?,?,?)",
                (kind, name, po_no, _now(), json.dumps(parsed)))
    con.commit()
    n = len(parsed["parts"]) if kind == "excel" else len(parsed["items"])
    what = {"excel": "TAFE Excel", "new": "New PO", "old": "Old PO"}[kind]
    return dict(kind=kind, name=name, po_no=po_no, count=n,
                message=f"{what} {po_no or parsed.get('doc', '')}: {n} {'parts' if kind == 'excel' else 'PO lines'}")


def files():
    out = {k: [] for k in KINDS}
    for r in rows("SELECT id, kind, name, po_no, uploaded_at, data FROM pc_files ORDER BY kind, po_no, name"):
        d = json.loads(r["data"])
        out[r["kind"]].append(dict(id=r["id"], name=r["name"], po_no=r["po_no"], uploaded_at=r["uploaded_at"],
                                   count=len(d.get("parts") or d.get("items") or []), doc=d.get("doc", "")))
    return out


def remove(fid=None, kind=None):
    con = get_db()
    if fid:
        con.execute("DELETE FROM pc_files WHERE id=?", (int(fid),))
    elif kind in KINDS:
        con.execute("DELETE FROM pc_files WHERE kind=?", (kind,))
    else:
        con.execute("DELETE FROM pc_files")
    con.commit()


def _load(kind):
    return [dict(json.loads(r["data"]), _name=r["name"]) for r in rows("SELECT name, data FROM pc_files WHERE kind=?", (kind,))]


def _plants():
    return {r["po_no"]: r["plant"] for r in rows("SELECT po_no, plant FROM po_headers")}


# ---------------------------------------------------------------- 1. Excel verifier
def excel_check():
    """Every part of TAFE's Excel against the new PO .htm files.
      Same            the PO has the revised price from the effective date, and the existing price before it
      Not amended     the PO has no price from the effective date yet (still the old one)
      Different       the PO has a price from that date, but not the Excel's revised price
      Existing differs  revised price right, but the price before the date is not the Excel's existing price
      Not in POs      the Excel part is in none of the new PO files uploaded
    and PO lines not in the Excel ('Not in Excel', for information)."""
    excel = _load("excel")
    pos = _load("new")
    if not excel:
        raise ValueError("Upload TAFE's Excel first")
    if not pos:
        raise ValueError("Upload the new PO .htm files first")
    plants = _plants()
    in_po = defaultdict(list)
    for po in pos:
        for it in po["items"]:
            in_po[it["part"]].append((po, it))
    out, seen = [], set()
    n = defaultdict(int)
    for x in excel:
        for p in x["parts"]:
            hits = in_po.get(p["part"])
            if not hits:
                out.append(dict(status="not_in_po", part=p["part"], descr=p["descr"], excel_doc=x["doc"],
                                excel_old=p["existing"], excel_new=p["revised"], effective=p["effective"],
                                note="Not in the new PO files uploaded"))
                n["not_in_po"] += 1
                continue
            for po, it in hits:
                seen.add((po["po_no"], it["part"]))
                eff = p["effective"] or ""
                before = (date.fromisoformat(eff) - timedelta(days=1)).isoformat() if eff else ""
                po_new = rate_on(it["blocks"], eff) if eff else None
                po_old = rate_on(it["blocks"], before) if before else None
                starts = sorted(_ymd(b["frm"]) for b in it["blocks"])
                amended = bool(eff) and eff in starts
                last = it["blocks"][-1] if it["blocks"] else None
                row = dict(part=p["part"], descr=p["descr"] or it["descr"], po_no=po["po_no"], line=it["item"],
                           plant=plants.get(po["po_no"]) or po.get("plant") or "", excel_doc=x["doc"],
                           excel_old=p["existing"], excel_new=p["revised"], effective=eff, po_old=po_old, po_new=po_new,
                           po_last=_block_rate(last) if last else None, po_last_from=_ymd(last["frm"]) if last else "")
                ok_new = po_new is not None and p["revised"] is not None and abs(po_new - p["revised"]) < 0.005
                ok_old = po_old is None or p["existing"] in (None, 0) or abs(po_old - p["existing"]) < 0.005
                if not amended and not ok_new:
                    row.update(status="not_amended", note=f"No price from {_dmy(eff)} in the PO yet"
                               if eff and last else "No effective date in the Excel")
                elif not ok_new:
                    row.update(status="different", diff=round(po_new - p["revised"], 2) if po_new is not None else None,
                               note=f"PO {po_new} from {_dmy(eff)}, Excel {p['revised']} (difference {round((po_new or 0) - p['revised'], 2):+})")
                elif not ok_old:
                    row.update(status="old_differs", diff=round(po_old - p["existing"], 2),
                               note=f"Revised price right; before {_dmy(eff)} the PO has {po_old}, Excel's existing price is {p['existing']}")
                else:
                    row.update(status="same", note="Same rate and date")
                n[row["status"]] += 1
                out.append(row)
    for po in pos:
        for it in po["items"]:
            if (po["po_no"], it["part"]) not in seen:
                last = it["blocks"][-1] if it["blocks"] else None
                out.append(dict(status="not_in_excel", part=it["part"], descr=it["descr"], po_no=po["po_no"], line=it["item"],
                                plant=plants.get(po["po_no"]) or po.get("plant") or "",
                                po_last=_block_rate(last) if last else None, po_last_from=_ymd(last["frm"]) if last else "",
                                note="PO line not in TAFE's Excel"))
                n["not_in_excel"] += 1
    order = dict(different=0, not_amended=1, old_differs=2, not_in_po=3, not_in_excel=4, same=5)
    out.sort(key=lambda r: (order[r["status"]], r.get("plant") or "", r.get("po_no") or "", r["part"]))
    return dict(summary=dict(n), rows=out, excel=[dict(doc=x["doc"], name=x["_name"], parts=len(x["parts"])) for x in excel],
                pos=len(pos))


# ---------------------------------------------------------------- 2. PO price changes (old PO -> new PO)
def price_changes():
    """Each part of each new PO: old price (old PO .htm, else the hub's PO data) -> new price.
    Old / new price = the price valid on the new PO's latest 'valid from' date, so a revision shows as
    old rate -> new rate from that date. Also lists every new price block the old PO did not have."""
    new = _load("new")
    if not new:
        raise ValueError("Upload the new PO .htm files first")
    old = {p["po_no"]: p for p in _load("old")}
    plants = _plants()
    hub = defaultdict(dict)
    nos = [p["po_no"] for p in new]
    if nos:
        for r in rows(f"SELECT po_no, part, item, blocks FROM po_items WHERE po_no IN ({','.join('?' * len(nos))})", tuple(nos)):
            b = [x for x in json.loads(r["blocks"] or "[]") if not x.get("tafe")]
            if b:
                hub[r["po_no"]][r["part"]] = b
    out = []
    n = defaultdict(int)
    tot = dict(old=0.0, new=0.0)
    for po in new:
        src = "old PO file" if po["po_no"] in old else ("hub PO data" if hub.get(po["po_no"]) else "")
        old_items = {it["part"]: it["blocks"] for it in old[po["po_no"]]["items"]} if po["po_no"] in old else hub.get(po["po_no"], {})
        for it in po["items"]:
            blocks = it["blocks"]
            last = blocks[-1] if blocks else None
            frm = _ymd(last["frm"]) if last else ""
            new_rate = _block_rate(last) if last else None
            row = dict(plant=plants.get(po["po_no"]) or po.get("plant") or "", po_no=po["po_no"], line=it["item"], part=it["part"],
                       issue=it.get("issue", ""), descr=it["descr"], uom=it["uom"], new_rate=new_rate, valid_from=frm, source=src)
            ob = old_items.get(it["part"])
            if ob is None:
                row.update(status="new_part", note="Not in the old PO" if src else "No old PO uploaded and not in the hub")
                n["new_part" if src else "no_old"] += 1
                if not src:
                    row["status"] = "no_old"
                out.append(row)
                continue
            old_last = ob[-1]
            old_rate = rate_on(ob, frm) if frm else None
            if old_rate is None:
                old_rate = _block_rate(old_last)
            ch = round((new_rate or 0) - (old_rate or 0), 2)
            pct = round(ch / old_rate * 100, 2) if old_rate else None
            added = [b for b in blocks if _ymd(b["frm"]) > _ymd(old_last["frm"])]
            row.update(old_rate=old_rate, old_from=_ymd(old_last["frm"]), change=ch, pct=pct,
                       status="increased" if ch > 0.004 else "decreased" if ch < -0.004 else "same",
                       revisions=[dict(frm=_ymd(b["frm"]), to=_ymd(b["to"]), rate=_block_rate(b)) for b in added],
                       note=(f"New price from {_dmy(frm)}" if added else "No new price block - same as the old PO")
                       if row.get("source") else "")
            if row["status"] == "same" and added:
                row["note"] = f"New block from {_dmy(frm)} with the same rate"
            n[row["status"]] += 1
            tot["old"] += old_rate or 0
            tot["new"] += new_rate or 0
            out.append(row)
        if po["po_no"] in old:              # parts dropped from the PO
            new_parts = {it["part"] for it in po["items"]}
            for it in old[po["po_no"]]["items"]:
                if it["part"] not in new_parts:
                    out.append(dict(plant=plants.get(po["po_no"]) or "", po_no=po["po_no"], line=it["item"], part=it["part"],
                                    descr=it["descr"], old_rate=_block_rate(it["blocks"][-1]) if it["blocks"] else None,
                                    status="removed", note="In the old PO, not in the new PO", source=src))
                    n["removed"] += 1
    order = dict(decreased=0, increased=1, new_part=2, removed=3, no_old=4, same=5)
    out.sort(key=lambda r: (order[r["status"]], r.get("plant") or "", r["po_no"], r["part"]))
    changed = [r for r in out if r["status"] in ("increased", "decreased")]
    avg = round(sum(r["pct"] for r in changed if r.get("pct") is not None) / len(changed), 2) if changed else 0
    return dict(summary=dict(n), avg_pct=avg, rows=out, pos=len(new), old_files=len(old))


# ---------------------------------------------------------------- Excel downloads
def to_xlsx(which):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    res = excel_check() if which == "excel" else price_changes()
    wb = Workbook()
    ws = wb.active
    if which == "excel":
        ws.title = "Excel vs PO"
        cols = [("Result", "status"), ("Plant", "plant"), ("PO No", "po_no"), ("PO Line", "line"), ("Part No", "part"),
                ("Description", "descr"), ("Excel doc", "excel_doc"), ("Excel existing", "excel_old"),
                ("Excel revised", "excel_new"), ("Effective", "effective"), ("PO before", "po_old"), ("PO from effective", "po_new"),
                ("PO latest price", "po_last"), ("PO latest from", "po_last_from"), ("Note", "note")]
        label = dict(same="Same", different="Different", not_amended="Not amended in PO", old_differs="Existing differs",
                     not_in_po="Not in POs", not_in_excel="Not in Excel")
    else:
        ws.title = "PO price changes"
        cols = [("Result", "status"), ("Plant", "plant"), ("PO No", "po_no"), ("PO Line", "line"), ("Part No", "part"),
                ("Issue", "issue"), ("Description", "descr"), ("UOM", "uom"), ("Old price", "old_rate"), ("Old from", "old_from"),
                ("New price", "new_rate"), ("New from", "valid_from"), ("Change (Rs)", "change"), ("Change %", "pct"),
                ("Old price from", "source"), ("Note", "note")]
        label = dict(increased="Increased", decreased="Decreased", same="No change", new_part="New part", removed="Removed",
                     no_old="No old price")
    ws.append([c[0] for c in cols])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1E3A5F")
    red, amber, green = (PatternFill("solid", fgColor=x) for x in ("FDE2E2", "FEF3C7", "DCFCE7"))
    for r in res["rows"]:
        vals = []
        for _, k in cols:
            v = r.get(k)
            if k == "status":
                v = label.get(v, v)
            elif k in ("effective", "po_last_from", "old_from", "valid_from") and v:
                v = _dmy(v)
            vals.append(v)
        ws.append(vals)
        fill = {"different": red, "decreased": red, "not_amended": amber, "old_differs": amber, "removed": amber,
                "same": green}.get(r["status"])
        if fill:
            ws.cell(row=ws.max_row, column=1).fill = fill
    for i, (h, _) in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = max(10, min(40, len(h) + 4)) if h not in ("Note", "Description") else 42
    ws.freeze_panes = "A2"
    s = wb.create_sheet("Summary", 0)
    s.append(["SDEW PO Price Check - " + ("TAFE Excel vs new PO" if which == "excel" else "Old PO vs new PO")])
    s.append(["Made", datetime.now().strftime("%d-%m-%Y %H:%M")])
    s.append([])
    for k, v in res["summary"].items():
        s.append([label.get(k, k), v])
    if which != "excel":
        s.append(["Average % change (changed parts)", res["avg_pct"]])
    s["A1"].font = Font(bold=True, size=13)
    s.column_dimensions["A"].width = 34
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
