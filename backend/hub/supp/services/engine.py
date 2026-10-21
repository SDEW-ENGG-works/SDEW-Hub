"""The supplementary bill calculation (same rules as the bills checked by hand in Oct 2026).

For every Tally sales line of a TAFE plant:
 1. Find its TAFE GRIN (GRIN files) by invoice + part; then same invoice + same qty;
    then the invoice number as TAFE mistyped it (5031//26-27, 1961/29-27 ...).
 2. PO = the PO on the GRIN, else the Tally order number (typos of the plant's main PO -> main PO).
 3. Existing Rate = PO price on old_date, Reversed Rate = PO price on new_date
    (Gross + Pkg.Charges + Freight); manual overrides from Settings win.
 4. Diff = Reversed - Existing (or Reversed - billed Rate), Basic Value = Diff x Billed Qty.
 5. Lines go to: Bill / GRN pending / old-date invoice / Excluded (with the reason).
"""
import json
import re
from collections import defaultdict
from datetime import datetime

from ..db import get_db, rows
from .defaults import SHORT_TERM_PREFIXES, load_settings
from .norm import fy_suffix, lead_number, part_key
from .po_parser import price_on


def _dmy(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}" if iso and len(iso) >= 10 else ""


def _words(t):
    return [w for w in re.split(r"[^A-Z0-9]+", (t or "").upper()) if w]


def same_name(a, b):
    """Tally and PO names of the same part: same words in any order (PO text may be cut short)."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return True
    short, long_ = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    hit = sum(1 for w in short if any(x == w or (len(w) >= 3 and x.startswith(w)) or (len(x) >= 3 and w.startswith(x))
                                    for x in long_))
    return hit >= max(1, round(len(short) * 0.6))


def run(params=None):
    s = load_settings()
    s.update(params or {})
    plants = {p["party"].strip(): p for p in s["plants"] if p.get("party")}
    overrides = {}
    for o in s.get("overrides", []):
        if o.get("part") and o.get("revised") not in (None, ""):
            ex = o.get("existing")
            overrides[part_key(o["part"])] = dict(revised=float(o["revised"]),
                                                  existing=float(ex) if ex not in (None, "") else None)
    old_day, new_day = s["old_date"], s["new_date"]

    sales = [r for r in rows("SELECT * FROM sales_lines ORDER BY voucher, part, seq") if r["party"].strip() in plants]
    # Tally part numbers typed wrong -> the PO part number (Settings)
    fixes = {}
    for c in s.get("part_corrections", []):
        fixes[((c.get("plant") or "").strip(), part_key(c["from"]))] = part_key(c["to"])
    for r in sales:
        code = plants[r["party"].strip()]["code"]
        to = fixes.get((code, r["part"])) or fixes.get(("", r["part"]))
        r["tally_part"] = None
        if to:
            r["tally_part"], r["part"] = r["part"], to
    rate_pending = {str(x).strip() for x in s.get("rate_pending_pos", []) if str(x).strip()}
    grns = rows("SELECT * FROM grin_lines ORDER BY grin_no, line_no")
    xl = {(r["voucher"], r["part"], r["seq"]): r for r in rows("SELECT * FROM grn_sheet")}
    po_items = defaultdict(dict)
    by_part = defaultdict(list)          # part -> [(po, old price, new price)] for the Existing Rate look-up
    for r in rows("SELECT po_no, part, descr, blocks FROM po_items"):
        b = json.loads(r["blocks"])
        po_items[r["po_no"]][r["part"]] = dict(descr=r["descr"], blocks=b)
        by_part[r["part"]].append((r["po_no"], price_on(b, old_day), price_on(b, new_day)))
    po_plant = {r["po_no"]: (r["plant"] or "") for r in rows("SELECT po_no, plant FROM po_headers")}
    main_pos = {(p.get("main_po") or "").strip() for p in s["plants"]}

    # billed rates per part (Existing Rate when a TAFE PO export has only the new rate)
    billed_rates = defaultdict(set)
    for r in sales:
        if r["rate"]:
            billed_rates[r["part"]].add(round(r["rate"], 2))

    # ---- GRIN matching ----------------------------------------------------
    for g in grns:
        g["pk"] = part_key(g["part_no"])
        g["inv"] = (g["invoice_no"] or "").strip()
    gseq, by_key = defaultdict(int), {}
    for g in grns:
        k = (g["inv"], g["pk"])
        by_key[(k[0], k[1], gseq[k])] = g
        gseq[k] += 1
    used, match, typed = set(), {}, {}
    for i, r in enumerate(sales):                                   # pass 1: invoice + part
        g = by_key.get((r["voucher"], r["part"], r["seq"]))
        if g:
            match[i] = g
            used.add(id(g))
    free = [g for g in grns if id(g) not in used]
    by_inv = defaultdict(list)
    for g in free:
        by_inv[g["inv"]].append(g)
    for i, r in enumerate(sales):                                   # pass 2: invoice + same qty
        if i in match:
            continue
        c = [g for g in by_inv.get(r["voucher"], []) if id(g) not in used and g["grin_qty"] == r["qty"]]
        if len(c) == 1:
            match[i] = c[0]
            used.add(id(c[0]))
    by_num = defaultdict(list)
    for g in grns:
        if id(g) in used:
            continue
        fy = fy_suffix(g["inv"])
        by_num[lead_number(g["inv"])].append((g, fy))
    for i, r in enumerate(sales):                                   # pass 3: mistyped invoice number
        if i in match:
            continue
        own_fy = fy_suffix(r["voucher"])
        c = [g for g, fy in by_num.get(lead_number(r["voucher"]), [])
             if id(g) not in used and (not fy or fy == own_fy) and (g["pk"] == r["part"] or g["grin_qty"] == r["qty"])]
        if len(c) == 1:
            match[i] = c[0]
            used.add(id(c[0]))
            typed[i] = c[0]["inv"]

    # ---- pricing + category -----------------------------------------------
    out = []
    for i, r in enumerate(sales):
        p = plants[r["party"].strip()]
        g = match.get(i)
        on = (r["order_no"] or "").strip()
        main = (p.get("main_po") or "").strip()
        if g and g["po_no"]:
            po = g["po_no"]
        elif on in po_items:
            po = on
        elif main and not on.startswith(SHORT_TERM_PREFIXES):
            po = main
        else:
            po = on
        first_po = po
        P = po_items.get(po, {})
        gp = g["pk"] if g else ""
        part = gp if gp in P else (r["part"] if r["part"] in P else (gp or r["part"]))
        it = P.get(part)

        def prices(po_, it_, pt=None):
            pt = pt or part
            o_, n_, src = price_on(it_["blocks"], old_day), price_on(it_["blocks"], new_day), "PO"
            if o_ is None and n_ is not None:
                # TAFE PO export gives only the new rate: take the Existing Rate from another PO
                # with the same part and the same new rate, else use the billed rate
                other = [(po2, o2) for po2, o2, n2 in by_part.get(pt, [])
                         if po2 != po_ and o2 is not None and n2 is not None and abs(n2 - n_) < 0.005]
                if other:
                    o_, src = other[0][1], f"PO {other[0][0]}"
                else:
                    # the rate billed just before the revision = highest billed rate below the new rate
                    below = [x for x in billed_rates.get(pt, ()) if x < n_ - 0.005]
                    o_, src = (max(below) if below else (r["rate"] or 0)), "billed rate"
            return o_, n_, src

        old = new = None
        old_src = "PO"
        if it:
            old, new, old_src = prices(po, it)
        moved_from = variant_of = None
        if (not it or old is None or new is None or round(new - old, 2) == 0) and part not in overrides:
            # this PO has no revision for the part - use another PO of the same plant that has one
            # (same part number and same part name), the plant's main PO first
            cands = []
            for po2, it2 in ((x, po_items[x].get(part)) for x in po_items if x != po):
                if not it2 or po_plant.get(po2) != p["code"] or not same_name(r["descr"], it2["descr"]):
                    continue
                o2, n2, src2 = prices(po2, it2)
                if o2 is not None and n2 is not None and round(n2 - o2, 2) > 0:
                    cands.append((po2 not in main_pos, src2 != "PO", po2, it2, o2, n2, src2))
            if not cands and not it and len(part) >= 8:
                # Tally part number not in any PO of the plant: a PO part that differs only in the last
                # two digits (drawing revision, e.g. 1520A01501 / 1520A01502), has the same name and
                # was billed by SDEW at the same rate is the same item typed with the old revision
                rate_ = round(r["rate"] or 0, 2)
                for po2 in po_items:
                    if po_plant.get(po2) != p["code"]:
                        continue
                    for pt2, it2 in po_items[po2].items():
                        if (pt2 == part or len(pt2) != len(part) or pt2[:-2] != part[:-2]
                                or not same_name(r["descr"], it2["descr"]) or rate_ not in billed_rates.get(pt2, ())):
                            continue
                        o2, n2, src2 = prices(po2, it2, pt2)
                        if o2 is not None and n2 is not None and round(n2 - o2, 2) > 0:
                            cands.append((po2 not in main_pos, src2 != "PO", po2, it2, o2, n2, src2, pt2))
            if cands:
                cands.sort(key=lambda c: c[:3])
                _, _, po2, it2, o2, n2, src2 = cands[0][:7]
                if len(cands[0]) > 7:
                    variant_of = part
                    part = cands[0][7]
                if po2 == po:
                    moved_from = None
                elif po not in po_items:
                    moved_from = f"{po or '(blank)'} (not uploaded)"
                elif not it:
                    moved_from = f"{po} (part not in it)"
                else:
                    moved_from = f"{po} (no price change)"
                po, it, old, new, old_src = po2, it2, o2, n2, src2
        ov = overrides.get(part)
        if ov:
            if ov["existing"] is not None and (it or po not in po_items):
                old, new, old_src = ov["existing"], ov["revised"], "Settings"
            elif old is not None:
                new = ov["revised"]
        x = xl.get((r["voucher"], r["part"], r["seq"]))
        xg = x["grn_no"] if x and x["grn_no"] else ""
        notes = []
        if g:
            grn, gdate = g["grin_no"], g["grin_date"]
            if xg and xg == grn:
                status = "Verified"
            elif xg:
                status = "Corrected"
                notes.append(f"GRN sheet had {xg}")
            else:
                status = "From GRIN file"
        elif xg:
            grn, gdate, status = xg, x["grn_date"], "GRN sheet only"
        else:
            grn, gdate, status = "", "", "No GRN"
        if g and gp and gp != r["part"]:
            notes.append(f"Tally part {r['part']}, TAFE GRIN part {gp}")
        if i in typed:
            notes.append(f"TAFE typed invoice as '{typed[i]}'")
        if g and g["grin_qty"] != r["qty"]:
            notes.append(f"GRIN qty {g['grin_qty']:g} vs billed {r['qty']:g}")
        if g and (g["rejected_qty"] or 0) > 0:
            notes.append(f"Rejected {g['rejected_qty']:g}")
        if r.get("tally_part"):
            notes.append(f"Tally part {r['tally_part']} corrected to {part} (Settings)")
        if variant_of:
            notes.append(f"Tally part {variant_of} not in any PO - taken as {part} (same name, same billed rate)")
        if moved_from:
            notes.append(f"Rate from PO {po} (same part & name, same plant); PO {moved_from}")
        if on and on != po and po in po_items:
            notes.append(f"Tally order no {on}")
        if old_src == "billed rate":
            notes.append("PO export has only the new rate - Existing Rate = last billed rate before it")
            if old and new / old > 1.065:
                notes.append(f"CHECK Existing Rate: +{(new / old - 1) * 100:.1f}% (usual revision ~5.7%)")
        elif old_src != "PO":
            notes.append(f"Existing Rate from {old_src}")

        rate = r["rate"] or 0
        if s["diff_basis"] == "billed" and new is not None:
            diff = round(new - rate, 2)
        elif old is not None and new is not None:
            diff = round(new - old, 2)
        else:
            diff = None

        if po not in po_items and old_src != "Settings":
            cat, reason = "Excluded", f"PO {po or '(blank)'} not uploaded"
        elif not it and old_src != "Settings":
            cat, reason = "Excluded", f"Part not in PO {po}"
        elif old is None or new is None:
            cat, reason = "Excluded", f"PO {po} has no price for {_dmy(old_day)} / {_dmy(new_day)}"
        elif old_src == "billed rate" and abs(rate - new) < 0.005 and s["remove_billed_at_revised"]:
            cat, reason = "Excluded", "Already billed at Reversed Rate"
        elif round(new - old, 2) == 0 and part not in overrides:
            cat, reason = "Excluded", "No price change"
        elif s["remove_billed_at_revised"] and abs(rate - new) < 0.005:
            cat, reason = "Excluded", "Already billed at Reversed Rate"
        elif diff is not None and diff <= 0:
            cat, reason = "Excluded", ("Billed rate not below Reversed Rate" if s["diff_basis"] == "billed"
                                       else "Reversed Rate lower than Existing Rate")
        elif not grn:
            cat, reason = "GRN pending", "No GRN yet"
        elif s["exclude_old_date_invoices"] and r["inv_date"] == old_day:
            cat, reason = "Old-date invoice", f"Invoice dated {_dmy(old_day)} (old rate valid that day)"
        else:
            cat, reason = "Bill", ""
        if cat == "Excluded" and rate_pending and not reason.startswith("Already billed"):
            # TAFE has not given the revised rate for these POs yet - keep them on the pending list
            rp = next((x for x in (first_po, po) if x in rate_pending), None) or next(
                (x for x in sorted(rate_pending) if part in po_items.get(x, {}) and po_plant.get(x) == p["code"]), None)
            if rp:
                cat, reason = "Rate pending", f"PO {rp}: revised rate not received from TAFE" + ("" if grn else "; no GRN yet")
                new = diff = None
        # a value is only shown for lines that can still be claimed (Bill, GRN pending, old-date invoices)
        value = round(diff * r["qty"], 2) if diff is not None and cat != "Excluded" else None
        out.append(dict(plant=p["code"], cat=cat, reason=reason, voucher=r["voucher"], inv_date=r["inv_date"],
                        party=r["party"], order_no=on, po_no=po, order_due=r["order_due"], part=part,
                        descr=(it["descr"] if it else r["descr"]) or r["descr"], hsn=r["hsn"], gst=r["gst"],
                        qty=r["qty"], rate=rate, old_rate=old, new_rate=new, diff=diff, value=value,
                        grn_no=grn, grn_date=gdate, status=status, notes="; ".join(notes), old_src=old_src))

    # ---- save the run --------------------------------------------------------
    summary = summarize(out)
    con = get_db()
    cur = con.execute("INSERT INTO bill_runs(created_at, params, summary) VALUES(?,?,?)",
                      (datetime.now().isoformat(timespec="seconds"),
                       json.dumps({k: s[k] for k in ("old_date", "new_date", "diff_basis", "overrides",
                                                    "remove_billed_at_revised", "exclude_old_date_invoices")}),
                       json.dumps(summary)))
    run_id = cur.lastrowid
    con.execute("DELETE FROM run_lines WHERE run_id NOT IN (SELECT id FROM bill_runs ORDER BY id DESC LIMIT 3)")
    cols = list(out[0].keys()) if out else []
    if cols:
        con.executemany(f"INSERT INTO run_lines(run_id,{','.join(cols)}) VALUES(?,{','.join('?' * len(cols))})",
                        [(run_id, *[o[c] for c in cols]) for o in out])
    con.commit()
    return dict(run_id=run_id, summary=summary)


def summarize(lines):
    plants = {}
    for l in lines:
        p = plants.setdefault(l["plant"], dict(plant=l["plant"], bill_lines=0, bill_qty=0, bill_value=0.0, gst=0.0,
                                                 cats={}))
        c = p["cats"].setdefault(l["cat"], dict(lines=0, value=0.0))
        c["lines"] += 1
        c["value"] = round(c["value"] + (l["value"] or 0), 2)
        if l["cat"] == "Bill" and l.get("old_src") == "billed rate":
            p["billed_basis_value"] = round(p.get("billed_basis_value", 0) + l["value"], 2)
            p["billed_basis_lines"] = p.get("billed_basis_lines", 0) + 1
        if l["cat"] == "Bill":
            p["bill_lines"] += 1
            p["bill_qty"] += l["qty"] or 0
            p["bill_value"] = round(p["bill_value"] + l["value"], 2)
            p["gst"] += l["value"] * (l["gst"] or 0) / 100
    for p in plants.values():
        p["gst"] = round(p["gst"], 2)
        p["bill_qty"] = round(p["bill_qty"], 3)
    order = [p["plant"] for p in sorted(plants.values(), key=lambda p: -p["bill_value"])]
    total = dict(bill_lines=sum(p["bill_lines"] for p in plants.values()),
                 bill_value=round(sum(p["bill_value"] for p in plants.values()), 2),
                 gst=round(sum(p["gst"] for p in plants.values()), 2))
    total["with_gst"] = round(total["bill_value"] + total["gst"], 2)
    reasons = defaultdict(int)
    for l in lines:
        if l["cat"] == "Excluded" and l["reason"].startswith("PO "):
            reasons[l["po_no"]] += 1
    missing = sorted(([po, n] for po, n in reasons.items()), key=lambda x: -x[1])
    return dict(plants=[plants[k] for k in order], total=total, missing_pos=missing[:40])


def latest_run_id():
    r = get_db().execute("SELECT id FROM bill_runs ORDER BY id DESC LIMIT 1").fetchone()
    return r[0] if r else None
