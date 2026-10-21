"""TAFE Channel 'PO Details' export (.xls, sheet 'Export Values').

    PO List for  PO Number : 1010016503| Vendor : ...| Plant : Doddaballapur Plant - 1030| PO Type : ALL
    Plant | PO Number | PO Date | Valid Till Date | ... | Part Details | Issue No | Currency | Rate(Rs) | ... | Price Effetc From

It gives only the CURRENT rate and the date it applies from - not the old rate.
So an item becomes one price block: Rate valid from 'Price Effetc From'.
The Existing (old) rate is then taken from another PO with the same part and the same new rate,
or, if there is none, from the billed rate (see engine.py).
"""
import re

from .norm import num, part_key, text, to_iso
from .readers import header_index, sheets


def looks_like_po_export(first_row):
    return bool(first_row) and str(first_row[0]).strip().startswith("PO List for")


def _dmy(iso):
    return f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}"


def parse(path, plant_codes=None):
    """-> list of po dicts (one file normally holds one PO)."""
    plant_codes = plant_codes or {}
    pos = {}
    for _, it in sheets(path):
        title = next(it, None)
        if not looks_like_po_export(title):
            continue
        t = str(title[0])
        m = re.search(r"Plant\s*:\s*(.*?)\s*-\s*(\d{4})", t)
        plant_name, plant_no = (m.group(1).strip(), m.group(2)) if m else ("", "")
        head = None
        for r in it:
            if head is None:
                if r and "PO Number" in [str(x).strip() for x in r]:
                    head = header_index(r)
                continue
            g = lambda k: r[head[k]] if k in head and head[k] < len(r) else None
            po_no = text(g("PO Number"))
            if not po_no:
                continue
            detail = text(g("Part Details"))
            part = part_key(detail.split(" - ")[0])
            if not part:
                continue
            rate = num(g("Rate(Rs)"), 0) or 0
            eff = to_iso(g("Price Effetc From") or g("Price Effect From"))
            if not eff or eff < "1990-01-01":   # TAFE shows 30/11/0002 when there is no date
                eff = "1900-01-01"
            po = pos.setdefault(po_no, dict(po_no=po_no, po_date=_dmy(to_iso(g("PO Date"))) if to_iso(g("PO Date")) else "",
                                            valid_till=_dmy(to_iso(g("Valid Till Date"))) if to_iso(g("Valid Till Date")) else "",
                                            bill_to=f"{plant_name} - {plant_no}",
                                            plant_hint=plant_codes.get(plant_no, ""), items=[], warnings=[]))
            # the same part can be on several PO lines (old lines left open): keep the latest price
            prev = next((x for x in po["items"] if x["part"] == part), None)
            if prev is not None:
                if eff <= prev["_eff"]:
                    continue
                po["items"].remove(prev)
            po["items"].append(dict(_eff=eff,
                item=int(num(g("PO Line Number"), 0) or 0), part=part, iss=text(g("Issue No")),
                descr=detail.split(" - ", 1)[1].strip() if " - " in detail else "", rate=rate, per=1,
                uom=text(g("Per UOM")) or "PC",
                blocks=[dict(frm=_dmy(eff), to="31.12.9999", conds=dict(rate=rate), export=True)]))
        break
    for po in pos.values():
        for it in po["items"]:
            it.pop("_eff", None)
    return list(pos.values())
