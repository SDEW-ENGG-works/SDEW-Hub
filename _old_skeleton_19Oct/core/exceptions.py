"""Everything that needs a person, across all modules, in one list.

Each rule is a SQL query over the unified tables. Rules return nothing until the
module data has been migrated or synced into the hub tables.
"""
from . import db


def _setting(key, default):
    r = db.rows("SELECT value FROM settings WHERE key=?", (key,))
    return r[0]["value"] if r and r[0]["value"] not in (None, "") else default


def rules():
    eway = float(_setting("eway_limit", 50000))
    grin_days = int(_setting("grin_pending_days", 15))
    return [
        ("chep", "Crates on invoice but no CHEP transfer",
         """SELECT i.invoice_no AS ref, i.invoice_date AS date, i.plant,
                   SUM(l.crates) || ' crates, ' || SUM(l.lids) || ' lids' AS detail
            FROM invoices i JOIN invoice_lines l ON l.invoice_id=i.id
            WHERE i.status='active' AND (l.crates>0 OR l.lids>0)
              AND NOT EXISTS (SELECT 1 FROM chep_transfers c WHERE c.invoice_no=i.invoice_no)
            GROUP BY i.id"""),
        ("dqms", "E-way bill missing above the limit",
         f"""SELECT invoice_no AS ref, invoice_date AS date, plant,
                    'Value ' || printf('%.2f', total) AS detail
             FROM invoices WHERE status='active' AND total>{eway}
               AND (eway_no IS NULL OR eway_no='')"""),
        ("dqms", "DR number is not 8 digits",
         """SELECT invoice_no AS ref, invoice_date AS date, plant, 'DR ' || dr_no AS detail
            FROM invoices WHERE dr_no IS NOT NULL AND dr_no<>''
              AND (length(dr_no)<>8 OR dr_no GLOB '*[^0-9]*')"""),
        ("grin", f"No GRIN after {grin_days} days",
         f"""SELECT i.invoice_no AS ref, i.invoice_date AS date, i.plant,
                    'Total ' || printf('%.2f', i.total) AS detail
             FROM invoices i WHERE i.status='active'
               AND i.invoice_date <= date('now', '-{grin_days} days')
               AND NOT EXISTS (SELECT 1 FROM grin g WHERE g.invoice_no=i.invoice_no)"""),
        ("pos", "Rate pending from TAFE",
         """SELECT po_no AS ref, po_date AS date, plant, COALESCE(notes,'') AS detail
            FROM pos WHERE rate_pending=1"""),
        ("masters", "Part on an invoice is not in the part master",
         """SELECT DISTINCT l.part_no AS ref, i.invoice_date AS date, i.plant,
                   'Invoice ' || i.invoice_no AS detail
            FROM invoice_lines l JOIN invoices i ON i.id=l.invoice_id
            WHERE l.part_no IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM parts p WHERE p.part_no=l.part_no)"""),
        ("pos", "Invoice rate differs from PO rate",
         """SELECT i.invoice_no AS ref, i.invoice_date AS date, i.plant,
                   l.part_no || ': billed ' || l.rate || ', PO ' || pp.rate AS detail
            FROM invoices i JOIN invoice_lines l ON l.invoice_id=i.id
            JOIN po_prices pp ON pp.po_no=i.po_no AND pp.part_no=l.part_no
            WHERE pp.effective_from = (SELECT MAX(effective_from) FROM po_prices x
                                       WHERE x.po_no=pp.po_no AND x.part_no=pp.part_no
                                         AND x.effective_from<=i.invoice_date)
              AND abs(l.rate - pp.rate) > 0.01"""),
    ]


def run():
    out = []
    for module, title, sql in rules():
        try:
            items = db.rows(sql)
        except Exception as e:  # keep the page working if one rule breaks
            items = []
            title += f" (rule error: {e})"
        out.append({"module": module, "title": title, "count": len(items), "items": items[:200]})
    return out
