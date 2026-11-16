"""Masters: one copy of every piece of shared data, kept fresh from its source.

  po_portal.py   TAFE Channel > PO Details reader (from Ore)
  po_master.py   PO master: m_po / m_po_lines / m_po_rates, published into po_headers / po_items
  sync.py        the 8 am / 9 pm TAFE Channel sync of every master + Refresh now + the sync_runs log
"""
