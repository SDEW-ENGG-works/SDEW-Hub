"""Default settings, taken from SDEW's filled template of 05-10-2026.

CHEP types: the packing list has one column per CHEP size. Older lists head these
columns 14400 / 14401 / 14402 / 14403, newer ones 0 / 1 / 2 / 3 / 8. Every CHEP on an
invoice becomes two template rows with the same quantity: the pallet SKU and its lid SKU.
"""
import copy

from ..db import get_setting

DEFAULT_SETTINGS = {
    "bp_code": "19177381",
    # Order here = order of the rows in the template (MDU first, as SDEW does it).
    "plants": [
        {"code": "MDU", "customer": "0019165124", "note": ""},
        {"code": "DBR", "customer": "0019165125", "note": ""},
    ],
    "types": [
        {"code": "0", "names": "0, 14400", "pallet": "A399014400", "lid": "A399013049"},
        {"code": "1", "names": "1, 14401", "pallet": "A399014401", "lid": "A399013052"},
        {"code": "2", "names": "2, 14402", "pallet": "A399014402", "lid": "A399013054"},
        {"code": "3", "names": "3, 14403", "pallet": "A399014403", "lid": "A399013054"},
        {"code": "8", "names": "8", "pallet": "", "lid": ""},
    ],
    "file_name": "BulkTransfer Template {date}.xlsx",
}


def load_settings():
    s = copy.deepcopy(DEFAULT_SETTINGS)
    saved = get_setting("app", {}) or {}
    for k in DEFAULT_SETTINGS:
        if k in saved:
            s[k] = saved[k]
    return s


def type_lookup(settings):
    """Header token in the packing list ('2', '14402', 'A399014402') -> type code."""
    out = {}
    for t in settings["types"]:
        code = str(t["code"]).strip()
        out[code.upper()] = code
        for n in str(t.get("names", "")).replace(";", ",").split(","):
            n = n.strip().upper()
            if n:
                out[n] = code
        if t.get("pallet"):
            out[str(t["pallet"]).strip().upper()] = code
    return out


def type_map(settings):
    return {str(t["code"]).strip(): t for t in settings["types"]}
