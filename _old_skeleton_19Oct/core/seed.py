"""First-run data: facts already confirmed in the Supplementary Bill, CHEP and DQMS apps."""
import datetime

PLANTS = [
    # code, name, tally_party, tafe_plant_code, chep_location, main_po, bill_to_word
    ("DBR", "Doddaballapur", "", "", "0019165125", "1210000691", "Doddaballapur"),
    ("MDU", "Madurai / Dindigul", "", "", "0019165124", "1030000676", "Dindigul"),
    ("SEMBIUM", "Sembium", "", "", "", "", "Sembium"),
]

CRATES = [
    ("0", "A399014400", "A399013049", "Crate size 0"),
    ("1", "A399014401", "A399013052", "Crate size 1"),
    ("2", "A399014402", "A399013054", "Crate size 2"),
    ("3", "A399014403", "A399013054", "Crate size 3"),
    ("8", "A399014408", "A399013054", "Auto 53348 Crate (found in Tally narrations, 16-Oct)"),
]

SETTINGS = [
    ("chep_bp", "19177381", "CHEP business partner number"),
    ("dqms_transporter", "DU6394", "Transporter code on every DQMS row"),
    ("supp_old_price_date", "01.04.2026", "Existing rate date"),
    ("supp_new_price_date", "02.04.2026", "Reversed rate date"),
    ("supp_diff_basis", "PO", "PO (Reversed - Existing) or billed rate"),
    ("eway_limit", "50000", "E-way bill needed above this invoice value"),
    ("chep_max_rows", "200", "LEAP reads only rows 2-201"),
    ("grin_pending_days", "15", "Flag an invoice with no GRIN after this many days"),
]

PART_CORRECTIONS = [("MDU", "1520A01501", "1520A01502", "Confirmed by user (Supplementary Bill)")]
FIXED_RATES = [("0714315M03", "ALL", None, 17.48, "Supplementary Bill fixed rate")]
POS = [("1010015475", "MDU", None, "seed", "open", 1,
        "Rate pending: 2330A3140169 Deflector RH, revised rate awaited from TAFE")]
REASONS = [(r, "DQMS reason for gap") for r in
           ["FG NOT AVAILABLE", "OTHERS", "EXTRA PULL BY TAFE", "LH AND RH MISMATCH", "VEH UTILIZATION"]]

OPEN_ITEMS = [
    ("supp", "Missing POs", "SPARE 1250002207, plus the SEMBIUM, R&D and FED POs."),
    ("supp", "Revised rate for PO 1010015475", "2330A3140169 Deflector RH - 5 lines on Rate pending."),
    ("supp", "Confirm 01.04.2026 rate for 6 CHECK parts",
     "3247A01601, 3427A05201, 3427A05701, 3427A05101, 4146A03201, 4186A04201."),
    ("supp", "Run Fetch GRIN on the live TAFE portal from the SDEW PC", ""),
    ("chep", "First live LEAP run", "Needs LEAP_USER / LEAP_PASS in .env and playwright on the PC."),
    ("chep", "299 invoices with crates in Tally but no CHEP transfer",
     "857 crates + lids, Jun-Sep 2026. Check physical dispatch before posting."),
    ("chep", "Set crate size 8 as a default", "A399014408 + lid A399013054 (already in Masters here)."),
    ("dqms", "PO line item question",
     "Manual upload used 23 / 487 (MDU PO); app uses 8 / 97 (DBR PO 1210000691). Confirm which the portal accepts."),
    ("dqms", "Invoice 13729 waiting for E-way Bill No.", "Value Rs 52,384."),
    ("hub", "Write migration mappers", "Run tools/inspect_legacy_dbs.py and map each old table into the unified tables."),
    ("hub", "Tally sync agent (future)", "Read invoices from Tally on port 9000 once on site at SDEW."),
]


def seed(con):
    if con.execute("SELECT COUNT(*) FROM plants").fetchone()[0]:
        return
    now = datetime.datetime.now().isoformat(timespec="seconds")
    con.executemany("INSERT INTO plants(code,name,tally_party,tafe_plant_code,chep_location,main_po,bill_to_word)"
                    " VALUES (?,?,?,?,?,?,?)", PLANTS)
    con.executemany("INSERT INTO crate_sizes VALUES (?,?,?,?)", CRATES)
    con.executemany("INSERT INTO settings VALUES (?,?,?)", SETTINGS)
    con.executemany("INSERT INTO part_corrections(plant,wrong_part,right_part,note) VALUES (?,?,?,?)",
                    PART_CORRECTIONS)
    con.executemany("INSERT INTO fixed_rates(part_no,plant,existing_rate,reversed_rate,note) VALUES (?,?,?,?,?)",
                    FIXED_RATES)
    con.executemany("INSERT INTO pos(po_no,plant,po_date,source,status,rate_pending,notes) VALUES (?,?,?,?,?,?,?)",
                    POS)
    con.executemany("INSERT INTO reason_codes VALUES (?,?)", REASONS)
    con.executemany("INSERT INTO open_items(module,title,detail,created_at) VALUES (?,?,?,?)",
                    [(m, t, d, now) for m, t, d in OPEN_ITEMS])
    con.commit()
