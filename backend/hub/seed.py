"""Follow-ups carried over from the three old apps (from their status notes, 12-19 Oct 2026).
Loaded once into open_items; afterwards they are ticked off / added on the Today page."""
from datetime import datetime

OPEN_ITEMS = [
    ("supp", "Missing POs", "SPARE 1250002207 (292 Excluded lines), plus the SEMBIUM, R&D and FED POs."),
    ("supp", "Revised rate for PO 1010015475", "2330A3140169 Deflector RH - 5 MDU lines wait on Rate pending."),
    ("supp", "Confirm the 01.04.2026 rate for 6 CHECK parts",
     "3247A01601, 3427A05201, 3427A05701, 3427A05101, 4146A03201, 4186A04201 (Existing Rate taken from the billed rate)."),
    ("supp", "Run Fetch GRIN against the live TAFE portal from the SDEW PC", "Needs TAFE_USER / TAFE_PASS in .env and Playwright."),
    ("chep", "First live LEAP run", "Needs LEAP_USER / LEAP_PASS in .env and Playwright on the PC."),
    ("chep", "299 invoices with crates in Tally but no CHEP transfer (Jun-Sep 2026)",
     "857 crates + lids. Check the physical dispatch before posting them."),
    ("chep", "Crate size 8 SKUs", "A399014408 'Auto 53348 Crate' + lid A399013054 - fill them in CHEP > Settings when confirmed."),
    ("dqms", "PO line item question",
     "First manual upload used 23 / 487 (MDU PO 1030000676); the app uses 8 / 97 from DBR PO 1210000691. Confirm which the portal accepts."),
    ("dqms", "Invoice 13729 waiting for its E-way Bill No.", "Value Rs 52,384 - the portal needs the 12-digit number above Rs 50,000."),
    ("hub", "Tally sync (on site)", "Read invoices straight from TallyPrime (port 9000) instead of the Sales Register export."),
]


def seed_open_items(con):
    try:
        if con.execute("SELECT COUNT(*) FROM open_items").fetchone()[0]:
            return
        now = datetime.now().isoformat(timespec="seconds")
        for m, t, d in OPEN_ITEMS:
            con.execute("INSERT INTO open_items(module,title,detail,status,created_at) VALUES(?,?,?,?,?)",
                        (m, t, d, "open", now))
        con.commit()
    except Exception:  # noqa: BLE001 - never block start-up
        pass
