-- SDEW Hub unified schema. One record per real-world thing, shared by every module.
-- Lifecycle: PO -> DR -> Invoice -> Dispatch/CHEP -> DQMS -> GRIN -> Supplementary bill

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY, value TEXT, note TEXT);

-- Masters ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plants (
  code TEXT PRIMARY KEY,            -- DBR / MDU / SEMBIUM
  name TEXT,
  tally_party TEXT,                 -- party ledger name in Tally
  tafe_plant_code TEXT,
  chep_location TEXT,               -- CHEP / LEAP location code
  main_po TEXT,
  bill_to_word TEXT,                -- word in the PO Bill-to address that identifies the plant
  active INTEGER DEFAULT 1);

CREATE TABLE IF NOT EXISTS parts (
  part_no TEXT PRIMARY KEY,
  description TEXT,
  hsn TEXT,
  gst_rate REAL,
  crate_size TEXT,                  -- CHEP size used last for this part
  dr_unit_size REAL,                -- pieces per DR bin
  notes TEXT);

CREATE TABLE IF NOT EXISTS part_corrections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  plant TEXT, wrong_part TEXT, right_part TEXT, note TEXT,
  UNIQUE(plant, wrong_part));

CREATE TABLE IF NOT EXISTS crate_sizes (
  size TEXT PRIMARY KEY, crate_sku TEXT, lid_sku TEXT, description TEXT);

CREATE TABLE IF NOT EXISTS fixed_rates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  part_no TEXT, plant TEXT DEFAULT 'ALL', existing_rate REAL, reversed_rate REAL, note TEXT);

CREATE TABLE IF NOT EXISTS reason_codes (
  code TEXT PRIMARY KEY, used_for TEXT);

-- Transactions ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS pos (
  po_no TEXT PRIMARY KEY, plant TEXT, po_date TEXT, source TEXT,
  status TEXT DEFAULT 'open', rate_pending INTEGER DEFAULT 0, notes TEXT);

CREATE TABLE IF NOT EXISTS po_lines (
  po_no TEXT, line_no INTEGER, part_no TEXT, description TEXT, qty REAL,
  PRIMARY KEY (po_no, line_no));

CREATE TABLE IF NOT EXISTS po_prices (
  po_no TEXT, part_no TEXT, effective_from TEXT,
  gross REAL, pkg REAL, freight REAL, rate REAL, source TEXT,
  PRIMARY KEY (po_no, part_no, effective_from));

CREATE TABLE IF NOT EXISTS drs (
  dr_no TEXT PRIMARY KEY, plant TEXT, po_no TEXT, part_no TEXT,
  unit_size REAL, units REAL, qty REAL, dr_date TEXT, status TEXT DEFAULT 'open', source TEXT);

CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_no TEXT NOT NULL, invoice_date TEXT, plant TEXT, party TEXT,
  po_no TEXT, dr_no TEXT, vehicle_no TEXT,
  taxable REAL, cgst REAL, sgst REAL, igst REAL, total REAL,
  eway_no TEXT, irn TEXT, narration TEXT,
  source TEXT,                      -- tally_sync / invoice_pdf / sales_register / packing_list
  status TEXT DEFAULT 'active',
  UNIQUE (invoice_no, invoice_date));

CREATE TABLE IF NOT EXISTS invoice_lines (
  invoice_id INTEGER, line_no INTEGER, part_no TEXT, description TEXT,
  qty REAL, rate REAL, amount REAL,
  crate_size TEXT, crates REAL DEFAULT 0, lids REAL DEFAULT 0,
  PRIMARY KEY (invoice_id, line_no));

CREATE TABLE IF NOT EXISTS chep_transfers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_no TEXT, plant TEXT, sku TEXT, qty REAL, doc_date TEXT,
  history_file TEXT, leap_status TEXT, source TEXT);

CREATE TABLE IF NOT EXISTS dqms_uploads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_no TEXT, file TEXT, status TEXT, message TEXT, uploaded_at TEXT);

CREATE TABLE IF NOT EXISTS grin (
  grin_no TEXT, line_no INTEGER, plant TEXT, invoice_no TEXT, part_no TEXT,
  qty REAL, grin_date TEXT, po_no TEXT,
  PRIMARY KEY (grin_no, line_no));

-- Hub ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  filename TEXT, kind TEXT, module TEXT, size INTEGER,
  path TEXT, received_at TEXT, status TEXT DEFAULT 'new', note TEXT);

CREATE TABLE IF NOT EXISTS open_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  module TEXT, title TEXT, detail TEXT,
  status TEXT DEFAULT 'open', created_at TEXT, done_at TEXT);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT, action TEXT, detail TEXT);
