"""Packing list lines -> CHEP Bulk Transfer rows.

For every invoice that goes in CHEPs:
  * the CHEP size comes from the size column ticked in the packing list (0/1/2/3/8);
  * when no size column is filled, the size last used for the same part is taken
    (learned from every packing list uploaded, or set on the Parts page);
  * otherwise the user picks it on the Create page (and it is remembered for the part).
Each CHEP size gives two template rows with the CHEP count as quantity: pallet SKU, lid SKU.
Invoices that go only in cartons are left out.
"""
from datetime import date, datetime

from ..db import get_db, rows as db_rows
from .defaults import type_map


def part_master():
    return {r["part"]: r for r in db_rows("SELECT part, type, part_name, source, updated_at FROM part_types")}


def learn(parsed, source):
    """Remembers the CHEP size used for each part (newest packing list sheet wins).
    Parts set by hand (source 'manual') are never overwritten."""
    master = part_master()
    seen = {}
    for s in sorted(parsed["sheets"], key=lambda s: s["date"] or ""):
        for ln in s["lines"]:
            sizes = {k: v for k, v in ln["sizes"].items() if not k.startswith("?")}
            if ln["part"] and sizes and ln["chep"] > 0:
                seen[ln["part"]] = (max(sizes, key=sizes.get), ln["part_name"])
    con = get_db()
    now = datetime.now().isoformat(timespec="seconds")
    n = 0
    for part, (code, pname) in seen.items():
        old = master.get(part)
        if old and old["source"] == "manual":
            continue
        if old and old["type"] == code:
            continue
        con.execute("INSERT INTO part_types(part,type,part_name,source,updated_at) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(part) DO UPDATE SET type=excluded.type, part_name=excluded.part_name, "
                    "source=excluded.source, updated_at=excluded.updated_at",
                    (part, code, pname, source, now))
        n += 1
    con.commit()
    return n


def remember_choices(lines):
    con = get_db()
    now = datetime.now().isoformat(timespec="seconds")
    for ln in lines:
        if ln["how"] == "chosen" and ln["part"]:
            code = next(iter(ln["types"]))
            con.execute("INSERT INTO part_types(part,type,part_name,source,updated_at) VALUES(?,?,?,?,?) "
                        "ON CONFLICT(part) DO UPDATE SET type=excluded.type, part_name=excluded.part_name, "
                        "source=excluded.source, updated_at=excluded.updated_at",
                        (ln["part"], code, ln["part_name"], "manual", now))
    con.commit()


def resolve(parsed, selected, choices, settings, sent=None, resend=()):
    """Every line of the selected sheets with the CHEP sizes it will use.

    sent: {invoice no: (file name, made on)} of invoices already in an earlier CHEP file
    (History). Packing list sheets are often copied from the day before and new rows added,
    so old invoices come back - those lines become "already" and are left out, unless the
    user presses "Send again" for them (resend)."""
    sent = sent or {}
    resend = set(resend or ())
    master = part_master()
    tmap = type_map(settings)
    out = []
    for s in parsed["sheets"]:
        if s["name"] not in selected:
            continue
        for ln in s["lines"]:
            r = dict(ln, sheet=s["name"], plant=s["plant"], types={}, how="", note="")
            known = {k: v for k, v in ln["sizes"].items() if not k.startswith("?")}
            unknown = [k[1:] for k in ln["sizes"] if k.startswith("?")]
            if ln["chep"] <= 0 and not ln["sizes"]:
                r["how"] = "carton"
                r["note"] = "Carton only - not in the CHEP template" if ln["carton"] else "No CHEP"
            elif choices.get(ln["key"]):
                r["types"] = {choices[ln["key"]]: ln["chep"] or sum(ln["sizes"].values())}
                r["how"] = "chosen"
            elif known and not unknown:
                r["types"] = known
                r["how"] = "packing list"
                if ln["chep"] and sum(known.values()) != ln["chep"]:
                    r["note"] = f"CHEP column says {ln['chep']}, size columns add up to {sum(known.values())} - size columns used"
            elif ln["part"] in master and not unknown:
                r["types"] = {master[ln["part"]]["type"]: ln["chep"]}
                r["how"] = "part history"
                r["note"] = "No size ticked in the packing list - size last used for this part"
            else:
                r["how"] = "missing"
                r["note"] = (f"Size column '{', '.join(unknown)}' is not set up in Settings > CHEP types" if unknown
                             else "No size ticked and this part has no CHEP size yet - choose one")
            for code in r["types"]:
                t = tmap.get(code)
                if not t or not t.get("pallet"):
                    r["how"] = "missing"
                    r["note"] = f"CHEP size {code} has no pallet SKU in Settings > CHEP types"
            prev = sent.get(ln["invoice"].strip())
            if prev and r["how"] != "carton":
                if ln["key"] in resend:
                    r["note"] = (r["note"] + " · " if r["note"] else "") + f"Already in {prev[0]} - sending again"
                    r["resent"] = True
                else:
                    r["how"] = "already"
                    r["note"] = f"Already sent in {prev[0]} (made {prev[1]}) - left out"
            out.append(r)
    return out


def build_rows(lines, settings, doc_date, extra):
    """Template rows, plant by plant in the Settings order."""
    tmap = type_map(settings)
    cust = {p["code"]: p["customer"] for p in settings["plants"]}
    order = {p["code"]: i for i, p in enumerate(settings["plants"])}
    use = [ln for ln in lines if ln["how"] not in ("carton", "missing", "already")]
    use.sort(key=lambda ln: order.get(ln["plant"], 99))  # stable: packing list order inside a plant
    out = []
    for ln in use:
        d = doc_date or (date.fromisoformat(ln["inv_date"]) if ln["inv_date"] else None)
        for code, n in ln["types"].items():
            t = tmap[code]
            for sku in (t["pallet"], t.get("lid")):
                if not sku:
                    continue
                out.append(dict(bp_code=settings["bp_code"], customer=cust.get(ln["plant"], ""), sku=sku, qty=n,
                                doc_date=d, transporter=extra.get("transporter", ""), vehicle=extra.get("vehicle", ""),
                                lr=extra.get("lr", ""), invoice=ln["invoice"], remarks=ln["part_name"],
                                plant=ln["plant"], type=code, key=ln["key"]))
    return out


def checks(lines, rows, settings, tinfo, doc_date):
    """Warnings shown above the preview (nothing here stops the download)."""
    warn = []
    plants = {p["code"]: p for p in settings["plants"]}
    for p in sorted({ln["plant"] for ln in lines}):
        if not p:
            warn.append("A ticked sheet has no plant - add its plant word (e.g. DBR / MDU) in Settings > Plants.")
        elif not plants.get(p, {}).get("customer"):
            warn.append(f"Plant {p} has no CHEP 'To Customer' code in Settings > Plants.")
    seen = {}
    for ln in lines:
        if ln["how"] != "carton":
            seen.setdefault(ln["invoice"], []).append(ln["sheet"])
    for inv, where in seen.items():
        if len(where) > 1:
            warn.append(f"Invoice {inv} is in the packing list {len(where)} times ({', '.join(sorted(set(where)))}).")
    ref = (tinfo or {}).get("reference") or {}
    if ref.get("bp_codes") and settings["bp_code"] not in ref["bp_codes"]:
        warn.append(f"BP Code {settings['bp_code']} is not in the template's Reference list.")
    if ref.get("customers"):
        bad = sorted({r["customer"] for r in rows if r["customer"] not in ref["customers"]})
        if bad:
            warn.append(f"To Customer {', '.join(bad)} not in the template's Reference list.")
    if ref.get("skus"):
        bad = sorted({r["sku"] for r in rows if r["sku"] not in ref["skus"]})
        if bad:
            warn.append(f"SKU {', '.join(bad)} not in the template's Reference list.")
    rng = (tinfo or {}).get("date_range")
    if rng and rng.get("start") and rows:
        ds = sorted({r["doc_date"].isoformat() for r in rows if r["doc_date"]})
        if ds and (ds[0] < rng["start"] or ds[-1] > rng["end"]):
            warn.append(f"Doc Date is outside the template's allowed range ({rng['start']} to {rng['end']}). "
                        "If the portal refuses the file, download a fresh blank template from the CHEP portal "
                        "and upload it in Settings.")
    if len(rows) > 200:
        warn.append(f"{len(rows)} rows - the CHEP portal reads only 200 rows per file, so the download will be "
                    "a .zip with separate files (each invoice kept whole). Upload every file in it.")
    return warn
