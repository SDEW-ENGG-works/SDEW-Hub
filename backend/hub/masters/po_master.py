"""PO master from TAFE Channel > PO Details.

  m_po        one row per PO (plant, PO date, valid till)
  m_po_lines  one row per PO line (part, rate, qty, delivered, Price Effect From) - replaced by every fetch
  m_po_rates  every rate ever seen for a PO line, with its Price Effect From - the rate history
  m_plants    TAFE's plant list (code, name)

The Supplementary Bill and DQMS read po_headers / po_items (date-wise price blocks). publish() writes the
master into them, so both modules use TAFE's POs without any change:
  * a PO part not there yet gets price blocks built from its rate history;
  * a part already there (e.g. from a PO .htm with older price blocks) keeps its blocks; when TAFE shows a
    new rate from a date, the blocks are cut at that date and the new rate is added from it.
"""
import json
from datetime import date, datetime, timedelta

from ..db import get_db, one, rows

FAR = "31.12.9999"


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _iso(d):
    return d.isoformat() if isinstance(d, date) else (d or None)


def _dmy(iso):
    return f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}" if iso else ""


def _ymd(dmy):
    return f"{dmy[6:10]}-{dmy[3:5]}-{dmy[0:2]}"


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def supplied_plants():
    """TAFE plant codes SDEW supplies: the TAFE plant codes set in Supplementary Bill > Settings > Plants."""
    from ..supp.services.defaults import load_settings
    out = {}
    for p in load_settings()["plants"]:
        code = str(p.get("grin_plant") or "").strip()
        if code:
            out[code] = p["code"]
    return out          # {"1030": "DBR", ...}


def save_plants(found):
    con = get_db()
    for code, name in found:
        con.execute("INSERT INTO m_plants(code, name, seen_at) VALUES(?,?,?) ON CONFLICT(code) DO UPDATE SET "
                    "name=excluded.name, seen_at=excluded.seen_at", (code, name, _now()))
    con.commit()


def save_rows(po_rows):
    """PO lines read from TAFE Channel -> the master. -> counts (and the POs touched, for publish)."""
    from .po_portal import group_by_po
    counts = dict(pos_new=0, pos_updated=0, lines_new=0, lines_updated=0, rate_changes=0, pos=[])
    if not po_rows:
        return counts
    con = get_db()
    now = _now()
    have_po = {r["po_no"] for r in rows("SELECT po_no FROM m_po")}
    have_line = {(r["po_no"], r["line_no"]): r for r in rows("SELECT po_no, line_no, rate, price_from FROM m_po_lines")}
    for po_no, g in group_by_po(po_rows).items():
        counts["pos_new" if po_no not in have_po else "pos_updated"] += 1
        con.execute("INSERT INTO m_po(po_no, plant, po_date, valid_till, fetched_at) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(po_no) DO UPDATE SET plant=excluded.plant, po_date=excluded.po_date, "
                    "valid_till=excluded.valid_till, fetched_at=excluded.fetched_at",
                    (po_no, g["plant"], _iso(g["po_date"]), _iso(g["valid_till"]), now))
        for line_no, r in g["lines"].items():
            old = have_line.get((po_no, line_no))
            counts["lines_new" if old is None else "lines_updated"] += 1
            rate, pfrom = _f(r["rate"]), _iso(r["price_from"])
            if old is not None and (abs(_f(old["rate"]) - rate) >= 0.005 or (old["price_from"] or None) != pfrom):
                counts["rate_changes"] += 1
            opt = lambda k, r=r: (None if r.get(k) is None else _f(r.get(k)))  # noqa: E731
            con.execute(
                "INSERT INTO m_po_lines(po_no, line_no, part, descr, issue_no, currency, rate, uom, total_qty, value, "
                "delivered_qty, price_from, price_confirmed, fetched_at, basic, freight, packing) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(po_no, line_no) DO UPDATE SET part=excluded.part, descr=excluded.descr, "
                "issue_no=excluded.issue_no, currency=excluded.currency, rate=excluded.rate, uom=excluded.uom, "
                "total_qty=excluded.total_qty, value=excluded.value, delivered_qty=excluded.delivered_qty, "
                "price_from=excluded.price_from, price_confirmed=excluded.price_confirmed, fetched_at=excluded.fetched_at, "
                "basic=excluded.basic, freight=excluded.freight, packing=excluded.packing",
                (po_no, line_no, r["part_no"], r["description"], r["issue_no"], r["currency"], rate, r["uom"],
                 _f(r["total_qty"]), _f(r["value"]), _f(r["delivered_qty"]), pfrom, _iso(r["price_confirmed"]), now,
                 opt("basic"), opt("freight"), opt("packing")))
            con.execute("INSERT OR IGNORE INTO m_po_rates(po_no, line_no, part, rate, price_from, first_seen) "
                        "VALUES(?,?,?,?,?,?)", (po_no, line_no, r["part_no"], rate, pfrom or "1900-01-01", now))
        counts["pos"].append(po_no)
    con.commit()
    return counts


# ---------------------------------------------------------------- publish into po_headers / po_items
def _blocks_from_history(hist):
    """[(price_from iso, rate)] sorted -> price blocks dd.mm.yyyy, each up to the day before the next one."""
    out = []
    hist = sorted(hist)
    for i, (frm, rate) in enumerate(hist):
        to = FAR
        if i + 1 < len(hist):
            to = _dmy((date.fromisoformat(hist[i + 1][0]) - timedelta(days=1)).isoformat())
        out.append(dict(frm=_dmy(frm), to=to, conds=dict(rate=round(rate, 2)), tafe=True))
    return out


def _merge(blocks, frm, rate):
    """Existing blocks + TAFE's current rate from 'frm' (iso). -> (blocks, changed)."""
    from ..supp.services.po_parser import price_on
    if frm == "1900-01-01":
        on = price_on(blocks, date.today().isoformat())
        if on is not None and abs(on - rate) < 0.005:
            return blocks, False
        if any(not (b.get("tafe") or b.get("export")) for b in blocks):
            return blocks, False                     # no date from TAFE: never override a full PO's blocks
        return [dict(frm="01.01.1900", to=FAR, conds=dict(rate=round(rate, 2)), tafe=True)], True
    on = price_on(blocks, frm)
    if on is not None and abs(on - rate) < 0.005:
        return blocks, False
    cut = (date.fromisoformat(frm) - timedelta(days=1)).isoformat()
    out = []
    for b in blocks:
        if _ymd(b["frm"]) >= frm:
            continue                                  # replaced by the new rate
        if _ymd(b["to"]) >= frm:
            b = dict(b, to=_dmy(cut))
        out.append(b)
    out.append(dict(frm=_dmy(frm), to=FAR, conds=dict(rate=round(rate, 2)), tafe=True))
    return out, True


def publish(po_nos=None):
    """Master -> po_headers / po_items (what the Supplementary Bill and DQMS read). -> counts."""
    con = get_db()
    plant_of = supplied_plants()
    where, args = "", ()
    if po_nos:
        where = f" WHERE po_no IN ({','.join('?' * len(po_nos))})"
        args = tuple(po_nos)
    heads = {r["po_no"]: r for r in rows("SELECT * FROM m_po" + where, args)}
    lines = rows("SELECT * FROM m_po_lines" + where + " ORDER BY po_no, line_no", args)
    hist = {}
    for r in rows("SELECT po_no, part, rate, price_from FROM m_po_rates" + where, args):
        hist.setdefault((r["po_no"], r["part"]), {})[r["price_from"]] = r["rate"]
    # the same part on several lines of one PO (old lines left open): the newest price wins
    best = {}
    for ln in lines:
        k = (ln["po_no"], ln["part"])
        cur = best.get(k)
        if cur is None or (ln["price_from"] or "") >= (cur["price_from"] or ""):
            best[k] = ln
    have = {(r["po_no"], r["part"]): r for r in rows("SELECT po_no, part, item, descr, uom, blocks FROM po_items" + where, args)}
    have_head = {r["po_no"]: r for r in rows("SELECT po_no, bill_to, file_id, source FROM po_headers" + where, args)}
    n = dict(pos=0, parts_new=0, parts_revised=0, parts_same=0)
    per_po = {}
    for (po_no, part), ln in best.items():
        per_po[po_no] = per_po.get(po_no, 0) + 1
        old = have.get((po_no, part))
        if old is None:
            h = sorted(hist.get((po_no, part), {}).items()) or [(ln["price_from"] or "1900-01-01", ln["rate"])]
            blocks = _blocks_from_history(h)
            n["parts_new"] += 1
            item, descr, uom = ln["line_no"], ln["descr"], ln["uom"] or "PC"
        else:
            before = json.loads(old["blocks"] or "[]")
            blocks, changed = _merge(before, ln["price_from"] or "1900-01-01", _f(ln["rate"]))
            n["parts_revised" if changed else "parts_same"] += 1
            if changed and not any(b.get("tafe") for b in before):
                # keep the PO file's price blocks as they were, for the comparison (m_po_prev)
                con.execute("INSERT OR IGNORE INTO m_po_prev(po_no, part, blocks, source, saved_at) VALUES(?,?,?,?,?)",
                            (po_no, part, json.dumps(before), (have_head.get(po_no) or {}).get("source") or "", _now()))
            item, descr, uom = old["item"] or ln["line_no"], old["descr"] or ln["descr"], old["uom"] or ln["uom"] or "PC"
        con.execute("INSERT OR REPLACE INTO po_items(po_no, part, item, descr, uom, rate, blocks) VALUES(?,?,?,?,?,?,?)",
                    (po_no, part, item, descr, uom, _f(ln["rate"]), json.dumps(blocks)))
    for po_no, cnt in per_po.items():
        h = heads.get(po_no) or {}
        old = have_head.get(po_no)
        items = one("SELECT COUNT(*) n FROM po_items WHERE po_no=?", (po_no,))["n"]
        plant = plant_of.get(str(h.get("plant") or ""), "")
        if old:
            con.execute("UPDATE po_headers SET plant=COALESCE(NULLIF(plant,''), ?), po_date=?, valid_till=?, items=?, "
                        "uploaded_at=? WHERE po_no=?",
                        (plant, _dmy(h.get("po_date")), _dmy(h.get("valid_till")), items, _now(), po_no))
        else:
            con.execute("INSERT INTO po_headers(po_no, plant, po_date, valid_till, bill_to, items, file_id, uploaded_at, "
                        "source) VALUES(?,?,?,?,?,?,?,?,?)",
                        (po_no, plant, _dmy(h.get("po_date")), _dmy(h.get("valid_till")), f"TAFE plant {h.get('plant')}",
                         items, None, _now(), "TAFE Channel PO Details"))
        n["pos"] += 1
    con.commit()
    return n


# ---------------------------------------------------------------- the fetch
def fetch(years=1, plants=None, budget=None, done=None, log=print):
    """Read PO Details for every supplied plant. years: how far back (TAFE allows one year per request).
    budget: seconds (website) - stops between requests and says more=True; done: windows finished before.
    -> dict(rows, pos, lines_new, rate_changes, published, more, done)."""
    import time
    from .po_portal import Channel, windows, year_back
    t0 = time.time()
    plant_of = supplied_plants()
    codes = plants or list(plant_of)
    if not codes:
        raise RuntimeError("No TAFE plant code is set: Supplementary Bill > Settings > Plants > TAFE plant code")
    done = set(done or [])
    ch = Channel()
    try:
        save_plants(ch.plants())
    except Exception as e:  # noqa: BLE001 - the POs can still be read
        log(f"Plant list not read: {e}")
    end = date.today()
    wins = windows(year_back(end, max(1, min(int(years), 4))), end)
    tot = dict(rows=0, pos_new=0, pos_updated=0, lines_new=0, lines_updated=0, rate_changes=0)
    touched, more = set(), False
    for code in codes:
        for a, b in wins:
            key = f"{code}:{a.isoformat()}"
            if key in done:
                continue
            if budget and time.time() - t0 > budget:
                more = True
                break
            got = ch.po_lines(code, a, b)
            c = save_rows(got)
            touched.update(c.pop("pos"))
            for k in ("pos_new", "pos_updated", "lines_new", "lines_updated", "rate_changes"):
                tot[k] += c[k]
            tot["rows"] += len(got)
            done.add(key)
            log(f"Plant {code} {plant_of.get(code, '')}: {a:%d/%m/%Y} - {b:%d/%m/%Y}: {len(got)} PO lines")
        if more:
            break
    # POs the hub already knows (from PO files) that the date window did not return - e.g. the 2017 schedule
    # POs valid till 2030 - are read by their PO number
    if not more:
        code_of = {v: k for k, v in plant_of.items()}
        known = {r["po_no"] for r in rows("SELECT po_no FROM m_po")}
        old_pos = [r for r in rows("SELECT po_no, plant FROM po_headers") if r["po_no"] not in known
                   and code_of.get(r["plant"]) in codes and f"po:{r['po_no']}" not in done]
        for r in old_pos:
            if budget and time.time() - t0 > budget:
                more = True
                break
            got = ch.po_by_number(code_of[r["plant"]], r["po_no"])
            c = save_rows(got)
            touched.update(c.pop("pos"))
            for k in ("pos_new", "pos_updated", "lines_new", "lines_updated", "rate_changes"):
                tot[k] += c[k]
            tot["rows"] += len(got)
            done.add(f"po:{r['po_no']}")
            log(f"PO {r['po_no']} ({r['plant']}) by number: {len(got)} PO lines")
    pub = publish(sorted(touched)) if touched else dict(pos=0, parts_new=0, parts_revised=0, parts_same=0)
    return dict(tot, published=pub, more=more, done=sorted(done))


# ---------------------------------------------------------------- compare with the PO files
def compare():
    """The PO master (TAFE Channel) against the prices loaded before from the PO .htm / export files.
    Per PO + part: the file's rate on TAFE's Price Effect From date (and today) vs TAFE's rate. TAFE's Rate(Rs)
    is compared both as it is and as Basic + Freight + Packing (a PO .htm block = Gross + Pkg + Freight)."""
    from ..supp.services.po_parser import price_on
    today = date.today().isoformat()
    prev = {(r["po_no"], r["part"]): json.loads(r["blocks"]) for r in rows("SELECT po_no, part, blocks FROM m_po_prev")}
    files = {}
    for r in rows("SELECT i.po_no, i.part, i.blocks, h.plant, h.source FROM po_items i LEFT JOIN po_headers h ON h.po_no=i.po_no"):
        b = prev.get((r["po_no"], r["part"]))
        if b is None:
            b = [x for x in json.loads(r["blocks"] or "[]") if not x.get("tafe")]
        if b:
            files[(r["po_no"], r["part"])] = dict(blocks=b, plant=r["plant"], source=r["source"] or "")
    tafe = {}
    for ln in rows("SELECT l.*, p.plant tafe_plant, p.valid_till FROM m_po_lines l JOIN m_po p ON p.po_no=l.po_no"):
        k = (ln["po_no"], ln["part"])
        if k not in tafe or (ln["price_from"] or "") >= (tafe[k]["price_from"] or ""):
            tafe[k] = ln
    names = supplied_plants()
    out, n = [], dict(match=0, differs=0, only_files=0, only_tafe=0)
    for k in sorted(set(files) | set(tafe)):
        f, t = files.get(k), tafe.get(k)
        row = dict(po_no=k[0], part=k[1], plant=(f or {}).get("plant") or names.get(str((t or {}).get("tafe_plant")), ""))
        if f and not t:
            row.update(status="only_files", file_rate=price_on(f["blocks"], today), note="Not in TAFE Channel's PO Details")
            n["only_files"] += 1
        elif t and not f:
            row.update(status="only_tafe", tafe_rate=t["rate"], price_from=t["price_from"], note="New from TAFE Channel")
            n["only_tafe"] += 1
        else:
            on = t["price_from"] or today
            fr = price_on(f["blocks"], on if on > "1990" else today)
            ft = price_on(f["blocks"], today)
            parts = [t.get("basic"), t.get("freight"), t.get("packing")]
            total = round(sum(x or 0 for x in parts), 2) if any(x is not None for x in parts) else None
            same = fr is not None and (abs(fr - (t["rate"] or 0)) < 0.01 or (total is not None and abs(fr - total) < 0.01))
            how = "" if not same else ("rate" if abs(fr - (t["rate"] or 0)) < 0.01 else "basic + freight + packing")
            row.update(status="match" if same else "differs", file_rate=fr, file_rate_today=ft, tafe_rate=t["rate"],
                       tafe_total=total, price_from=t["price_from"], line_no=t["line_no"],
                       note=f"same ({how})" if same else
                       ("file has no price on that date" if fr is None else f"difference {round((t['rate'] or 0) - fr, 2):+}"))
            n["match" if same else "differs"] += 1
        out.append(row)
    order = dict(differs=0, only_files=1, only_tafe=2, match=3)
    out.sort(key=lambda r: (order[r["status"]], r["plant"] or "", r["po_no"], r["part"]))
    return dict(summary=n, rows=out, master=summary())


def summary():
    s = one("SELECT COUNT(*) pos, MAX(fetched_at) fetched FROM m_po") or {}
    ln = one("SELECT COUNT(*) n FROM m_po_lines") or {}
    today = date.today().isoformat()
    open_ = one("SELECT COUNT(*) n FROM m_po WHERE valid_till IS NULL OR valid_till >= ?", (today,)) or {}
    return dict(pos=s.get("pos") or 0, lines=ln.get("n") or 0, open_pos=open_.get("n") or 0, fetched=s.get("fetched"))


def search(q="", plant="", only_open=False, limit=500):
    sql = ("SELECT l.*, p.plant, p.po_date, p.valid_till FROM m_po_lines l JOIN m_po p ON p.po_no=l.po_no WHERE 1=1")
    args = []
    if q:
        sql += " AND (l.part LIKE ? OR l.po_no LIKE ? OR l.descr LIKE ?)"
        args += [f"%{q.strip().upper()}%", f"%{q.strip()}%", f"%{q.strip()}%"]
    if plant:
        sql += " AND p.plant=?"
        args.append(plant)
    if only_open:
        sql += " AND (p.valid_till IS NULL OR p.valid_till >= ?)"
        args.append(date.today().isoformat())
    sql += " ORDER BY p.po_date DESC, l.po_no, l.line_no LIMIT ?"
    args.append(int(limit))
    out = rows(sql, tuple(args))
    names = supplied_plants()
    for r in out:
        r["plant_short"] = names.get(str(r["plant"]), "")
        r["balance_qty"] = max((r["total_qty"] or 0) - (r["delivered_qty"] or 0), 0)
        r["history"] = rows("SELECT rate, price_from, first_seen FROM m_po_rates WHERE po_no=? AND line_no=? "
                            "ORDER BY price_from", (r["po_no"], r["line_no"])) if q else []
    return out
