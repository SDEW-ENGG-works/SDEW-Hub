"""Default settings of the GRIN & Payments module. Everything here can be changed on its Settings tab."""

DEFAULT_SETTINGS = {
    # invoices older than this many days with no GRIN -> reminder mail to the buyer
    # (TAFE usually GRINs in 3 days, 9 in 10 within 7 days - checked on Apr-Oct 2026 data)
    "wait_days": 7,
    # TAFE pays within this many days of GRIN (half in 6 days, 9 in 10 within 18 days) -> later = overdue
    "credit_days": 21,
    # do not send the same invoice again within this many days
    "resend_days": 3,
    # after this many reminders for an invoice, the escalation CC is added
    "escalate_after": 2,
    "escalate_cc": "",
    # invoices dated before this are not checked
    "from_date": "2026-04-01",
    # when filled, EVERY mail goes to this address instead of the buyer (for testing)
    "test_to": "",
    "mail_subject": "GRIN pending - Sri Durga Engg. Works invoices ({count})",
    "mail_intro": "Dear {name},\n\nThe following Sri Durga Engg. Works invoices were delivered to TAFE {plant} "
                  "but are not yet GRINed on TAFE Channel. Kindly arrange to GRIN the parts at the earliest.",
    "signature": "Thanks & regards,\nAccounts\nSri Durga Engg. Works",
    # plants whose Tally party has no TAFE GRIN plant code (R&D, FED, J REHAB) are not checked
    "track_plants_without_grin": False,
    # TAFE payment doc types that are not invoice payments (KG = cash discount)
    "ignore_doc_types": ["KG"],
    # TallyPrime XML server (F1 Help > Settings > Connectivity: TallyPrime acts as Both, port 9000)
    "tally_url": "http://localhost:9000",
    # one Tally company per location; empty = the company open in Tally
    "tally_companies": [],
}


def load_settings():
    from ..db import get_setting
    s = dict(DEFAULT_SETTINGS)
    saved = get_setting("app", {}) or {}
    s.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
    return s


def plants():
    """Tally party -> plant, shared with the Supplementary Bill (Settings > Plants there)."""
    from ...supp.services.defaults import load_settings as supp_settings
    return supp_settings()["plants"]
