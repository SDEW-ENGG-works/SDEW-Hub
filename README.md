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

## Payments (`/pay/`, added 22-Oct-2026)
The separate Payment Marking app moved into the hub (`backend/hub/pay/`, `frontend/pay/`, tables `pm_*` and `ps_*`).
- **Payment marking** – same as the old app: register + TAFE PaymentDetailsExport → voucher no / date marked in the
  register (credit = paid, credit + ZK debit note = marked as before, ZK alone / KG not). The payment export and the
  register (also the marked one) are passed on to GRIN & Payments too, so its "paid" status stays current.
- **Sales marking** – the TAFE SALES DETAILS file (`INVOICE NO … PART NO … QTY | GRN QTY | GRN NO | GRN DATE`):
  GRN NO, GRN DATE (dd/mm/yyyy) and GRN QTY = TAFE **accepted** qty from the hub's GRIN lines.
  Match per invoice: same part → part starting with the other → one line each side / same qty. Inspection not
  finished (accepted 0, rejected 0) → GRN QTY blank. A GRN NO / QTY already in the file is never changed unless ticked
  ("GRN no differs"). Parties without a TAFE GRIN plant code (Supp Bill › Settings › Plants) are skipped.
  **Fetch GRIN** on that tab = the Supp Bill's TAFE Channel fetch (on the website the SDEW PC does it); the check runs again after it.
- The marked file becomes the file for the next check (both tabs). Hub drop box: payment export, register and
  TAFE SALES DETAILS go to Payments.
- First run on 22-Oct (sales file up to 21-Oct, GRIN up to 20-Oct): 14,511 lines → 527 GRN filled, 13,143 GRN QTY added,
  28 short/rejected, 2 inspection open, 49 GRN no differs (typed GRN shifted by a row, mostly April), 409 GRIN pending,
  22 not in GRIN data, 331 not a GRIN party. Typed GRN NO agreed with TAFE on 13,170 of 13,219.
- The old app (`Downloads\SDEW\PaymentMarking`, repo SDEW-ENGG-works/Payment-marking) is retired.


## Logins and the Admin page (23-Oct-2026)
`ADMIN_USER` / `ADMIN_PASS` in the env = the administrator: every page + **Admin** (top right) at `/admin/`.
On the Admin page: create users (username, password, the pages they may open, note), change pages, set a new password,
switch a user off, delete. A user sees only their boxes, and the server refuses every other page and `/api/...`
(403). Users are in the `users` table (PBKDF2 password hashes). The old shared `APP_PASSWORD` still logs in
(leave the username empty) with every page but no Admin - remove it from the env when everyone has a login.
Code: `backend/hub/auth.py` (who may open what: `needs()`), `handlers/admin.py`, `frontend/admin/`.

## Security and data recovery (29-Oct-2026)

| What | How it works |
|---|---|
| **Nightly backup** | The hub on the SDEW PC copies **every table** of the database it uses (Turso or `data\sdew_hub.db`) into `data\backups\sdew_hub_<date>_<time>_nightly.zip` (inside: `sdew_hub.db` + `manifest.json`). After 21:00 (`BACKUP_HOUR`); a PC that was off at night does it as soon as the hub starts. Kept 30 days (`BACKUP_KEEP_DAYS`). |
| **Second copy** | `BACKUP_COPY_DIR` in `.env` (e.g. `G:\My Drive\SDEW Hub backups` with Google Drive for desktop) gets a copy of every backup, so a dead PC loses nothing. |
| **Website backups (no PC)** | With a **Vercel Blob** store connected (Vercel > project > Storage > Create > Blob, *Private*), the website makes and restores backups itself: Admin > Back up now / Restore work without the PC, and Vercel Cron calls `/api/cron/backup` every night at 21:00 IST (`vercel.json` `crons`, 15:30 UTC). Files: `backups/sdew_hub_<date>_<time>_<reason>.zip` in the private store, kept 30 days. Set `CRON_SECRET` in the Vercel env so only Vercel Cron can call it. Put `BLOB_READ_WRITE_TOKEN` in the PC's `.env` too and the PC's backups are also kept in Blob. |
| **Back up now / Restore** | Admin page > Backups. Restore asks you to type RESTORE, makes a "before-restore" backup first (so a restore can be undone), then refills every table. Logins, the backup list and the activity list are kept. On the website these run as jobs on the SDEW PC (it must be on). A backup file can be downloaded on the PC hub. |
| **Clear data = admin only** | The "Clear data" cards are hidden for other users and the server refuses them (403). DQMS "Start fresh" stays open (daily work). Every clear first copies the rows into `wipe_snapshots` / `wipe_rows`; Admin > Cleared data > **Put back** restores them. |
| **Who did what** | Every change (upload, file made, setting saved, delete, login, failed login, backup, restore) is in the activity list with the user's name (`activity.user`). |
| **Lockout** | 5 wrong passwords for one username → locked 15 minutes (works across the PC and the website: table `login_fails`). Admin > Locked logins > Unlock. |
| **Browser protections** | Every answer carries Content-Security-Policy (only this site + Google Fonts + the Tally Bridge on localhost:9001), X-Frame-Options DENY, nosniff, Referrer-Policy, Permissions-Policy, and HSTS on the website. A change sent from another website is refused. Uploads above `MAX_UPLOAD_MB` (50) are refused with 413. |

Code: `backend/hub/services/backup.py`, `services/safety.py`, `security.py`; Admin page `frontend/admin/`.
Tested 29-Oct on a copy of the data through a mock Turso server: backup = exact copy of every table; restore after
deleting half the GRIN lines brought every table back exactly; clear-data + put back; lockout; 413 / cross-site refusal;
website "Back up now" handed to the PC agent; all pages load with the new browser rules (no blocked content).
