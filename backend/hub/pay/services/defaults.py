"""Default settings. Everything here can be changed on the Settings page."""

DEFAULT_SETTINGS = {
    # invoice that has a payment credit AND a debit note (ZK) in the export: mark it like a normal
    # received invoice (this is how it was done by hand before, e.g. 12783, 12820, 12790)
    "mark_credit_debit": True,
    # TAFE pays the invoice amount less ~0.1 % TDS. A credit outside this band is shown as
    # "Amount differs" (it is still marked unless you untick it)
    "min_ratio": 0.985,
    "max_ratio": 1.002,
    "mark_amount_differs": True,
    # colour columns A-F of a marked row? Off: only the voucher no + date are written, and the row is
    # coloured green by hand after checking it (user's choice, 29-Oct-2026)
    "fill_rows": False,
    # the colour used when fill_rows is on (same green as the register)
    "fill_color": "92D050",
    # doc types that are not invoice payments (cash discount etc.) - ignored when matching
    "ignore_doc_types": ["KG"],
}


def load_settings():
    from ..db import get_setting
    s = dict(DEFAULT_SETTINGS)
    saved = get_setting("app", {}) or {}
    s.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
    return s
