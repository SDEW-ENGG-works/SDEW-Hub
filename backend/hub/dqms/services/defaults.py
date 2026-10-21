"""App settings (Settings page). Stored in the settings table under "app"."""
from ..db import get_setting

# Column headings of TAFE's blank DQMS template (template.csv downloaded from TAFE Channel).
TEMPLATE_HEADER = [
    "Record Flag*", "DR No.*", "Order No.*", "PO Line Item No.*", "Part No.*", "Reason for Gap", "Remarks",
    "Invoice No.*", "Invoice Date(dd.MM.yyyy)*", "Invoice Unit*", "Final Invoice Value*", "CGST", "SGST", "IGST",
    "E-way Bill No.", "E-Way Bill Valid From (dd.MM.yyyy HH:mm)", "E-Way Bill Valid To (dd.MM.yyyy HH:mm)",
    "Transporter*", "LR No.", "LR Date (dd.MM.yyyy)", "No. of Packages", "Weight in Kgs", "Type of Vehicle",
    "Vehicle Number", "Start Date (dd.MM.yyyy)", "Batch Details Applicable", "Batch No.",
    "Batch Qty. to be Consumed", "Batch Considerable (Yes / No)", "Remarks when Batch Considerable 'No'",
]

DEFAULT_SETTINGS = {
    "transporter": "DU6394",
    "batch_applicable": "YES",
    "batch_considerable": "YES",
    # the portal's "Reason for Gap" drop-down
    "reasons": ["FG NOT AVAILABLE", "OTHERS", "EXTRA PULL BY TAFE", "LH AND RH MISMATCH", "VEH UTILIZATION"],
    "invoice_unit": "packages",       # packages = "No of Packeges" on the invoice, one = always 1
    "batch_order": "oldest",          # oldest batch first (FIFO)
    "file_name": "template_{date}.csv",
    "header": TEMPLATE_HEADER,
}


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    s.update({k: v for k, v in (get_setting("app") or {}).items() if k in DEFAULT_SETTINGS})
    return s
