"""Default settings. Everything here can be changed on the Settings page."""

DEFAULT_SETTINGS = {
    # price on old_date = Existing Rate, price on new_date = Reversed (revised) Rate
    "old_date": "2026-04-01",
    "new_date": "2026-04-02",
    # Reversed Rate fixed by hand for a part, in every plant
    "overrides": [
        {"part": "0714315M03", "revised": 17.48, "note": "Same as MDU PO 1030000676, for all plants"},
    ],
    # Tally part number typed wrong: use the correct (PO) part number. plant "" = every plant
    "part_corrections": [
        {"plant": "MDU", "from": "1520A01501", "to": "1520A01502", "note": "Tally typo - TAFE PO has 1520A01502"},
    ],
    # POs whose revised rate TAFE has not given yet: their lines go to the pending list, not Excluded
    "rate_pending_pos": ["1010015475"],
    # rows already billed at the Reversed Rate need no supplementary bill
    "remove_billed_at_revised": True,
    # invoices dated on old_date were correctly billed at the old rate
    "exclude_old_date_invoices": True,
    # "po": Diff = Reversed - Existing (PO prices)   "billed": Diff = Reversed - billed Rate
    "diff_basis": "po",
    # Tally party -> plant. bill_to = word in the PO "Bill to" address; grin_plant = TAFE plant code
    "plants": [
        {"code": "DBR", "party": "Tractors and Farm Equipment Ltd - B", "grin_plant": "1030",
         "main_po": "1210000691", "bill_to": "Doddaballapur"},
        {"code": "MDU", "party": "Tractors and Farm Equpment Ltd", "grin_plant": "1000",
         "main_po": "1030000676", "bill_to": "Kalladipatti"},
        {"code": "SEMBIUM", "party": "Tractor and Farm Equpment Ltd - SEMBIUM", "grin_plant": "1040",
         "main_po": "", "bill_to": "Sembiam"},
        {"code": "IBU", "party": "TRACTORS AND FARM EQUIPMENT LTD - IBU", "grin_plant": "1140",
         "main_po": "1080002068", "bill_to": "INTERNATIONAL BUSINESS"},
        {"code": "SPARE", "party": "TRACTORS AND FARM EQUIPMENT LTD  - SPARE", "grin_plant": "1125",
         "main_po": "1250002207", "bill_to": "SPARE PARTS"},
        {"code": "PUDUPAKKAM", "party": "TRACTORS AND FARM EQUIPMENT - PUDUPAKKAM", "grin_plant": "1042",
         "main_po": "", "bill_to": "Pudupakkam"},
        {"code": "R&D", "party": "6 - TRACTORS AND FARM EQUIPMENT LTD - R&D", "grin_plant": "",
         "main_po": "", "bill_to": ""},
        {"code": "FED", "party": "Tractors and Farm Equipment  -FED", "grin_plant": "",
         "main_po": "", "bill_to": ""},
        {"code": "J REHAB", "party": "M/S, TRACTORS & FARM EQUIPMENT LIMITED - J REHAB", "grin_plant": "",
         "main_po": "", "bill_to": ""},
    ],
}

# order numbers starting with these are short-term POs, never a typo of the plant's main PO
SHORT_TERM_PREFIXES = ("1010", "2010", "2040", "2100", "5030", "10010")


def load_settings():
    from ..db import get_setting
    s = dict(DEFAULT_SETTINGS)
    saved = get_setting("app", {}) or {}
    s.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
    return s
