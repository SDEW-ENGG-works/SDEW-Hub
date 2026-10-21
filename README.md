# SDEW Hub

One app for the TAFE order-to-payment work at Sri Durga Engg. Works:

**PO → DR → invoice → packing list / CHEP → DQMS → GRIN → supplementary bill**

It joins the three apps — **Supplementary Bill** (port 8020), **CHEP Transfer** (8030) and **DQMS Upload** (8040) —
into one program, one database and one address: **http://localhost:8050**.
(Attendance & Salary and ManufAI stay separate, as decided.)

## Start

1. Keep this folder where it is (`Downloads\SDEWHub\SDEWHub`). The old apps stay in `Downloads\SDEW`.
2. `pip install -r requirements.txt` (the same packages the old apps already use).
3. Double-click **start.bat**.
   On the **first** start it copies all the data of the three old apps into `data\sdew_hub.db`, checks it
   (see *Verified* below) and opens the hub. Every later start just opens it.

The old apps are only **read** — their folders and databases are never changed, and they keep working.
Close them before starting the hub only if you want the ports free; the hub uses 8050.

The first start also copies the TAFE / LEAP logins and APP_PASSWORD from the old `.env` files into the hub's `.env`.

## What is in the hub

| Page | What it does |
|---|---|
| **Today** (`/`) | The chain with counts, the supplementary bill total by plant, **Needs attention** (checks across all modules), follow-ups, recent activity |
| **Find & trace** | Type any invoice / part / PO / DR / GRIN number. An invoice opens its **whole trail**: Tally line → DR → packing list → CHEP file → DQMS file + portal status → GRIN → supplementary bill line |
| **Drop files** | One box for every file — the hub works out what each file is and hands it to the right module |
| **Follow-ups** | The open questions from the three apps, plus your own; tick off when done |
| **Masters** | Plants, CHEP sizes, DQMS reasons, fixed rates, part corrections, logins — side by side |
| **Supplementary Bill** (`/supp/`) | Bill, Uploads, POs, GRIN (Fetch GRIN), Review, Settings — same as the old app |
| **CHEP Transfer** (`/chep/`) | Create, History, Parts, LEAP, Settings — same as the old app |
| **DQMS Upload** (`/dqms/`) | Create, History, POs, Settings — same as the old app |
| **GRIN & Payments** (`/grin/`) | Every TAFE invoice: GRINed? paid? Not GRINed → reminder mail to the plant's buyer (see below) |

The search box in the dark bar at the top works on every page. Links like `/supp/#grin` open that tab.

### Shared data (the point of the hub)
* **POs are stored once.** A PO `.htm` or TAFE PO export dropped anywhere is used by the bill
  (Existing / Reversed Rate) **and** by DQMS (PO line item). No more "Import from Supplementary Bill app".
* One login (APP_PASSWORD) for everything, one `.env`, one database, one backup.

## Tools

| Command | What it does |
|---|---|
| `python tools\import_from_apps.py --check` | Compare the old apps with the hub, change nothing |
| `python tools\import_from_apps.py` | Copy the old apps' data in again (hub data is backed up to `data\backups\` first) |
| `python tools\verify_hub.py` | Prove the hub = the old apps (writes `data\verify_report.txt`) |
| `python tools\upload_to_cloud.py` | Copy the hub's data to a Turso cloud database (for the website) |

**Where the data comes from:** Supplementary Bill from `SupplementaryBill\data\supp_bill.db` (not hosted); CHEP from its Turso cloud database (the live data); DQMS from its Turso cloud database merged with `DQMSUpload\data\dqms.db` (same invoice → the one saved last, History files from both, batches from the newer DQMS report). The Turso keys are copied into the hub `.env` as `CHEP_TURSO_*` and `DQMS_TURSO_*`.
If Turso cannot be reached, the PC copy is used and the import says so — then double-click **import_data.bat** when online.

## Verified (19-Oct-2026, on a copy of the PC's data)
* Every row of every table of the three apps is in the hub, field for field (13,689 sales lines,
  13,349 GRIN lines, 13,410 GRN-sheet lines, 77 POs / 913 part lines, 40,557 bill lines, 13 packing lists,
  111 CHEP part sizes, 792 DQMS batches, all History files …).
* The supplementary bill calculated again in the hub is **identical line by line** to the old app's
  bill of 12-Oct: 12,684 lines, basic **₹62,37,479.71**, with GST **₹65,64,793.89**.
* Every CHEP History file rebuilt from its packing list gives the same rows.
* Every DQMS History CSV is the same, byte for byte.

## Layout
```
server.py                 run on the PC (port 8050)        vercel_app.py   run on Vercel
backend/hub/              config, db (one database), http router, auth, turso, local_server, wsgi
backend/hub/handlers/     /api/hub/...  Today, search, trails, drop box, follow-ups, masters
backend/hub/services/     insight.py (checks, trails), router.py (which module a file is for)
backend/hub/supp|chep|dqms/   the three apps' code (services + handlers), routes under /api/supp|chep|dqms/
frontend/                 hub page + login;  frontend/supp|chep|dqms/  the three apps' pages
tools/                    import_from_apps.py, verify_hub.py, upload_to_cloud.py
data/                     sdew_hub.db, uploads\supp|chep|dqms, grin_downloads, leap, dqms_downloads, backups
```
Tables keep their old names; only the three History tables were renamed (`bill_runs`, `chep_runs`, `dqms_runs`)
and settings keys carry the module name (`supp.app`, `chep.app`, `dqms.app`, `dqms.dqms_report`).

## Online (optional)
Same as the old apps: GitHub → Vercel (`pyproject.toml` points at `vercel_app.py`) with a **new** Turso database
(`TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `APP_PASSWORD` in Vercel's environment variables).
`python tools\upload_to_cloud.py` copies the PC's data up; `USE_CLOUD_DB=1` in `.env` makes the PC use it too,
and then the CHEP website → PC LEAP agent works through it as before.
Fetch GRIN, the DQMS report button and LEAP upload need Playwright and run on the PC only.


## GRIN & Payments (`/grin/`, added 21-Oct-2026)

**Tally invoice → TAFE GRIN → TAFE payment**, one status per invoice:
Not GRINed (older than 7 days, no GRIN → remind) · GRIN short / rejected · Payment overdue (GRINed > 21 days, unpaid) ·
Awaiting payment · GRIN pending (younger than 7 days) · Debit note only · Paid. Days are counted only up to the date the
GRIN / payment data covers, so an old download never makes an invoice look late.

**Get data** tab, in order:
1. **Pull from Tally** — TallyPrime's XML server (F1 Help › Settings › Connectivity › Client/Server: *Both*, port 9000).
   One request per company and month; Sales vouchers of the TAFE parties (Settings › Plants of the Supplementary Bill).
   Companies (one per location) on Settings. The last answer is kept in `data\tally\` to check by hand.
   Without Tally: the Sales Register upload (already in the hub) or a Day Book XML export works too.
2. **Fetch GRIN** — the same TAFE Channel fetch as the Supplementary Bill (one copy of the GRIN data).
3. **Drop** the TAFE `PaymentDetailsExport*.xls` and (optional) the invoice register
   (`INVOICE NO | INVOICE DATE | AMOUNT | plant | payment details | payment date`) for values and older payments.

**Reminders** tab: one mail per buyer (Buyers tab: plant → name / e-mail / CC; a PO line overrides its plant),
not again within 3 days, escalation CC after 2 reminders, *Send test mails to* for a dry run.
Sending needs SMTP in `.env`: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `MAIL_FROM` (Gmail: App Password).
Without SMTP: *Download .eml* → send from Outlook → *Mark sent*.
Invoice detail (click a row): parts, GRIN lines, payment lines, mails, a note and **Hold** (no reminders).
Today page: *Paid by TAFE* step, a GRIN & Payments card and two checks (not GRINed / payment overdue).

Code: `backend/hub/grin/` (services: tally, payments, status, mailer, ingest), `frontend/grin/`. Tables `gp_*`.

## One database for the PC and the website (21-Oct-2026)
`TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` = the hub's **primary** database (Mumbai). Everything lives there:
Supplementary Bill, CHEP, DQMS, GRIN & Payments, follow-ups.

1. Create the Mumbai database, put its two keys in this PC's `.env` (keep the `CHEP_TURSO_*` / `DQMS_TURSO_*` lines).
2. `python tools\build_primary_db.py --check` then `python tools\build_primary_db.py` - merges this PC's hub data with
   the live CHEP and DQMS website databases (website rows win, PC-only rows added) and uploads it.
3. Add `USE_CLOUD_DB=1` to `.env`, restart `start.bat`. Same two keys in Vercel > Environment Variables, redeploy.

Without `TURSO_DATABASE_URL` the website falls back to reading the old CHEP / DQMS databases for those two pages.

**Pull from Tally / Fetch GRIN on the website** are done by the SDEW PC: the website puts a job in `pc_jobs`, the hub
on the PC (start.bat, `USE_CLOUD_DB=1`) picks it up within seconds, runs it and writes the log back
(`backend/hub/services/pc_jobs.py`). The Get data tab shows whether the SDEW PC is online. If the PC is offline,
Fetch GRIN on the website tries TAFE Channel directly (no browser, `supp/services/grin_http.py`).

## Pull from Tally on the website = the Tally of the computer you are using (21-Oct-2026)
The browser reads Tally through the **Tally bridge** (`tally_bridge.bat` / `tools\tally_bridge.py`, port 9001) running on
the same computer, and sends the answers to the website week by week (gzip, under Vercel's 4.5 MB limit).
On every computer that has Tally: download **SDEW-Tally-Bridge.exe** (link on the Get data tab, or the copy in this folder)
and double-click it once - it installs itself to `%LOCALAPPDATA%\SDEW`, runs hidden and starts with Windows
(`--uninstall` removes it; source in `tools\tally_bridge_go\`). `tally_bridge.bat` (Python) does the same job without installing.
Only the hub's pages (sdew-hub*.vercel.app, localhost:8050) may use the bridge. Chrome/Edge ask once to allow
"access to devices on your local network" - press Allow. The hub on a PC (localhost:8050) still pulls its own Tally directly.
