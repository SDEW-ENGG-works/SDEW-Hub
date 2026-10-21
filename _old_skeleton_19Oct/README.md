# SDEW Hub

One app for the TAFE order-to-payment work at SDEW:
PO -> DR -> Invoice -> Dispatch & CHEP -> DQMS -> GRIN -> Supplementary bill.
(Attendance & Salary stays a separate app. Tally sync comes later, on site.)

## Install
1. Unzip so this folder sits next to the existing apps:
   C:\Users\abhin\Downloads\SDEW\SDEWHub
   (next to SupplementaryBill, CHEPTransfer, DQMSUpload)
2. Optional: `pip install -r requirements.txt` (better file recognition).
3. Optional: copy `.env.example` to `.env` and set APP_PASSWORD.
4. Double-click `start.bat`. On the first run it copies the three apps into `legacy\`,
   then opens http://localhost:8050.

## The original folders are never changed
`tools\setup_from_existing.py` only reads them: code is copied (without .git), databases are
copied through SQLite's backup API from a read-only connection.
- Refresh only the databases: `python tools\setup_from_existing.py --data`
- Re-copy code too: `python tools\setup_from_existing.py --code`

Close the old apps before starting their copies from the hub - both use the same ports
(8020 / 8030 / 8040). From now on, work in the copies.

## What's in the hub
| Page | What it does now |
|---|---|
| Today | The 7-step chain with counts, checks that need attention, open items, app status |
| Drop files | One drop box. Recognises PO htm, TAFE export, GRIN, Sales Register, packing list, LEAP MIS, DQMS report, DR / invoice PDFs, DQMS status, and stores them in `data\inbox` |
| POs, DRs, Invoices, GRIN | Unified tables (filled once the migration mappers are written) |
| Dispatch & CHEP, DQMS, Supplementary bill | The copied app running inside the hub |
| Needs attention | Cross-step checks: crates not transferred, E-way bill missing, bad DR no, no GRIN, rate pending, unknown part, billed rate vs PO rate |
| Open items | Follow-ups carried over from all apps |
| Masters | Plants, parts, crate sizes (incl. size 8), part corrections, fixed rates, reason codes, settings |
| Old app data | Read-only view of every table in the copied databases |

## Layout
```
server.py              routes + static files (standard library only)
core/config.py         paths, .env, list of copied apps
core/schema.sql        unified tables
core/seed.py           confirmed facts from the existing apps
core/db.py             hub DB + read-only access to copied DBs
core/recognize.py      what kind of file is this
core/exceptions.py     the "needs attention" checks
core/legacy.py         start / stop the copied apps
core/auth.py           password login
tools/                 setup_from_existing.py, inspect_legacy_dbs.py
static/                index.html, style.css, app.js
legacy/                copies of the old apps (created by setup)
data/                  hub.db, inbox, legacy_schema.md
```

## Next steps
1. Run `python tools\inspect_legacy_dbs.py` and share `data\legacy_schema.md` to write the
   mappers that move POs, GRIN, invoices, CHEP history and DQMS history into the unified tables.
2. Move each module's logic out of `legacy\` into the hub, one step at a time, starting with POs.
3. Build the Tally sync agent on site (reads invoices from Tally on port 9000).
