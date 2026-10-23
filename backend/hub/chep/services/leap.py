"""Uploads a CHEP file to LEAP (my.leap-india.com), waits for the user's OK, submits it,
then downloads 'Pending Inwards at C2' and checks every invoice - like a person would,
with Playwright. Runs only on the PC (needs a browser):

    pip install playwright        python -m playwright install chromium
    .env:  LEAP_USER=...   LEAP_PASS=...

Page details checked on the live site on 14-Oct-2026:
  login        #empCode, #password, button[type=submit]  -> /dashboard
  upload       /bulk-transfer-out : input[type=file] (accept .xlsx,.xls); the page reads the file
               itself and shows buttons "ALL (n)", "CLEAN (n)", "ERROR (n)"; SUBMIT posts /bulkTROut
               and LEAP processes it as a background job (Jobs Tracker), then e-mails a result CSV.
  report       /reports : Report select -> "Pending Inwards at C2" -> Download Report gives
               Pending_Inwards_At_C2_<dd-mm-yyyy>_<bp>_Customer.csv
The one thing we never do on our own is press SUBMIT: the app waits for the user's OK.
"""
import io
import json
import os
import re
import threading
import time
import traceback
import zipfile
from datetime import datetime

from .. import config
from .. import db as cdb
from ..db import get_db, one
from .reconcile import parse_pending_csv, problem_rows, reconcile

BASE = (os.environ.get("LEAP_URL") or "https://my.leap-india.com").rstrip("/")
REPORT_NAME = "Pending Inwards at C2"
CONFIRM_WAIT = 30 * 60        # user has 30 minutes to press Submit
JOB_WAIT = 10 * 60            # LEAP background job
VERIFY_TRIES = 4              # report re-downloaded if invoices are still missing
VERIFY_GAP = int(os.environ.get("LEAP_VERIFY_GAP") or 60)

_lock = threading.Lock()
# Live view: the newest screenshot of the LEAP page (JPEG). Shown on the LEAP page of whoever is
# looking - the browser itself always runs hidden (headless) on the machine doing the job.
SHOT = {"ts": 0.0, "jpg": None, "seq": 0}
_PAGE = {"page": None, "thread": None}
_decision = threading.Event()
STATE = {}


def _reset(**kw):
    SHOT.update(ts=0.0, jpg=None)
    STATE.clear()
    STATE.update(active=True, phase="running", run_id=None, file_name="", mode="", headed=False,
                 started=datetime.now().isoformat(timespec="seconds"), finished="", error="",
                 steps=[], parts=[], current=None, log=[], verify=None, retry_run_id=None,
                 decision=None, submit_message="")
    STATE.update(kw)


def snapshot():
    return json.loads(json.dumps(STATE or dict(active=False, phase="idle"), default=str))


def available():
    if config.ON_VERCEL:
        return False, "Works only in the app on the SDEW PC (it opens a browser)."
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False, "Playwright is not installed. On the PC run:  pip install playwright   then   python -m playwright install chromium"
    env = config.read_env()
    if not env.get("LEAP_USER") or not env.get("LEAP_PASS"):
        return False, "Put LEAP_USER and LEAP_PASS (the LEAP login) in the .env file next to server.py."
    return True, ""


# ---------------------------------------------------------------- state helpers
def _log(msg):
    STATE["log"].append(f"{datetime.now():%H:%M:%S}  {msg}")
    STATE["log"] = STATE["log"][-200:]
    print("[LEAP]", msg)


def _snap(force=False):
    """Screenshot of the LEAP page for the live view (only from the worker thread, max 1 a second)."""
    page = _PAGE["page"]
    if page is None or threading.current_thread() is not _PAGE["thread"]:
        return
    now = time.time()
    if not force and now - SHOT["ts"] < 1.0:
        return
    try:
        SHOT["jpg"] = page.screenshot(type="jpeg", quality=50)
        SHOT["ts"] = now
        SHOT["seq"] += 1
    except Exception:  # noqa: BLE001 - page busy / navigating: next time
        pass


def _wait(page, ms):
    """page.wait_for_timeout in small pieces, keeping the live view fresh."""
    end = time.time() + ms / 1000.0
    while True:
        left = end - time.time()
        if left <= 0:
            break
        page.wait_for_timeout(int(min(left, 1.0) * 1000))
        _snap()


def _step(key, label=None, status=None, detail=None):
    for s in STATE["steps"]:
        if s["key"] == key:
            break
    else:
        s = dict(key=key, label=label or key, status="todo", detail="")
        STATE["steps"].append(s)
    if label:
        s["label"] = label
    if status:
        s["status"] = status
    if detail is not None:
        s["detail"] = detail
    _snap(force=True)
    return s


def _run_parts(run):
    """[(part file name, bytes, row count)] of a History file (.xlsx or .zip of parts)."""
    import openpyxl
    data = bytes(run["xlsx"])
    if run["file_name"].lower().endswith(".zip"):
        z = zipfile.ZipFile(io.BytesIO(data))
        files = [(n, z.read(n)) for n in sorted(z.namelist(), key=lambda n: [int(x) if x.isdigit() else x
                                                                             for x in re.split(r"(\d+)", n)])]
    else:
        files = [(run["file_name"], data)]
    out = []
    for name, b in files:
        ws = openpyxl.load_workbook(io.BytesIO(b), read_only=True).worksheets[0]
        n = sum(1 for r in ws.iter_rows(min_row=2, values_only=True) if any(v not in (None, "") for v in r))
        out.append((name, b, n))
    return out


# ---------------------------------------------------------------- public
def start(run_id, mode="upload", headed=False):
    ok, why = available()
    if not ok:
        raise RuntimeError(why)
    run = one("SELECT id, file_name, rows, xlsx FROM chep_runs WHERE id=?", (run_id,))
    if not run:
        raise RuntimeError("That file is not in History any more.")
    with _lock:
        if STATE.get("active") and STATE.get("phase") in ("running", "waiting"):
            raise RuntimeError("LEAP is already busy with another file - wait for it to finish or press Cancel.")
        _reset(run_id=run_id, file_name=run["file_name"], mode=mode, headed=bool(headed))
    _decision.clear()
    spec = cdb.current()   # the worker uses the same CHEP database as the caller (see leap_remote)

    def _go():
        cdb.use(spec)
        _worker(run_id, mode, bool(headed))
    threading.Thread(target=_go, daemon=True).start()
    return snapshot()


def decide(choice):
    if STATE.get("phase") != "waiting":
        raise RuntimeError("Nothing is waiting for a decision.")
    STATE["decision"] = choice
    _decision.set()
    return snapshot()


def cancel():
    if STATE.get("phase") == "waiting":
        return decide("cancel")
    if STATE.get("phase") == "running":
        STATE["decision"] = "cancel"
        _decision.set()
        _log("Cancel asked - stopping after the current step")
    return snapshot()


def _cancelled():
    return STATE.get("decision") == "cancel"


# ---------------------------------------------------------------- worker
def _worker(run_id, mode, headed):
    from playwright.sync_api import sync_playwright
    out_dir = os.path.join(config.DATA_DIR, "leap")
    os.makedirs(out_dir, exist_ok=True)
    run = one("SELECT id, batch_id, file_name, rows, xlsx FROM chep_runs WHERE id=?", (run_id,))
    run_rows = json.loads(run["rows"] or "[]")
    page = None
    try:
        parts = _run_parts(run) if mode == "upload" else []
        _step("login", "Log in to LEAP")
        for i, (name, _, n) in enumerate(parts):
            STATE["parts"].append(dict(name=name, rows=n, all=None, clean=None, error=None, errors=[],
                                       submitted=False, message=""))
            _step(f"upload{i}", f"Upload {'part ' + str(i + 1) + ' of ' + str(len(parts)) if len(parts) > 1 else 'file'}"
                  f" ({n} rows)")
            _step(f"check{i}", "LEAP check: ALL / CLEAN / ERROR")
            _step(f"submit{i}", "Your OK, then SUBMIT in LEAP")
        if parts:
            _step("job", "LEAP processes the transfer")
        _step("report", f"Download '{REPORT_NAME}' report")
        _step("verify", "Check every invoice")

        with sync_playwright() as p:
            # always hidden: the person watches it in the live view on the LEAP page instead
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(accept_downloads=True, viewport={"width": 1400, "height": 900})
            page = ctx.new_page()
            _PAGE.update(page=page, thread=threading.current_thread())
            api_log = []
            page.on("response", lambda r: api_log.append(r) if "bulkTROut" in r.url else None)
            try:
                _login(page)
                for i, (name, data, n) in enumerate(parts):
                    if _cancelled():
                        raise _Stop()
                    safe = re.sub(r"[^\w.() -]", "_", name)
                    path = os.path.join(out_dir, f"run{run_id}_{i + 1}_{safe}")
                    with open(path, "wb") as fh:
                        fh.write(data)
                    _upload_and_submit(page, i, path, n, api_log)
                if parts:
                    _wait_job(page)
                _verify(page, run, run_rows, out_dir)
                STATE["phase"] = "done"
                _log("Finished")
            except _Stop:
                STATE["phase"] = "cancelled"
                _log("Stopped - nothing more was sent to LEAP")
                for s in STATE["steps"]:
                    if s["status"] in ("todo", "doing", "waiting"):
                        s["status"] = "skip"
            except Exception:
                shot = os.path.join(out_dir, f"error_{datetime.now():%Y%m%d_%H%M%S}.png")
                try:
                    page.screenshot(path=shot, full_page=True)
                    _log(f"Screenshot of the LEAP page saved: {shot}")
                except Exception:  # noqa: BLE001
                    pass
                raise
            finally:
                _snap(force=True)
                _PAGE.update(page=None, thread=None)
                browser.close()
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        STATE["phase"] = "error"
        STATE["error"] = str(e)
        for s in STATE["steps"]:
            if s["status"] in ("doing", "waiting"):
                s["status"] = "error"
                s["detail"] = str(e)[:300]
        _log(f"Stopped: {e}")
        _save_status(run_id, "error", dict(error=str(e)))
    finally:
        STATE["finished"] = datetime.now().isoformat(timespec="seconds")
        if STATE.get("phase") == "running":
            STATE["phase"] = "error"


class _Stop(Exception):
    pass


def _login(page):
    env = config.read_env()
    _step("login", status="doing")
    _log("Opening my.leap-india.com")
    page.goto(BASE + "/", wait_until="domcontentloaded")
    _wait(page, 1500)
    if page.locator("#empCode").count():
        page.fill("#empCode", env["LEAP_USER"])
        page.fill("#password", env["LEAP_PASS"])
        page.click("button[type=submit]")
        try:
            page.wait_for_url(re.compile(r".*/dashboard.*"), timeout=60_000)
        except Exception:  # noqa: BLE001
            raise RuntimeError("LEAP login failed - check LEAP_USER / LEAP_PASS in .env")
    who = ""
    try:
        who = page.evaluate("localStorage.getItem('bpName') || ''")
    except Exception:  # noqa: BLE001
        pass
    _step("login", status="done", detail=f"Logged in{(' as ' + who) if who else ''}")
    _log("Logged in")


def _count(page, label):
    loc = page.locator("button", has_text=re.compile(rf"^\s*{label}\s*\(\d+\)\s*$"))
    if not loc.count():
        return None
    m = re.search(r"\((\d+)\)", loc.first.inner_text())
    return int(m.group(1)) if m else None


def _counts(page):
    return dict(all=_count(page, "ALL"), clean=_count(page, "CLEAN"), error=_count(page, "ERROR"))


def _click_confirm_if_any(page, wait_ms=4000):
    sel = (".ant-modal-confirm-btns .ant-btn-primary, .ant-popconfirm-buttons .ant-btn-primary, "
           ".ant-modal-footer .ant-btn-primary")
    try:
        page.locator(sel).first.wait_for(state="visible", timeout=wait_ms)
        page.locator(sel).first.click()
        _log("Confirmed LEAP's pop-up")
        return True
    except Exception:  # noqa: BLE001
        return False


def _upload_and_submit(page, i, path, expected, api_log):
    part = STATE["parts"][i]
    STATE["current"] = i
    _step(f"upload{i}", status="doing")
    _log(f"Opening Bulk Transfer Out ({os.path.basename(path)})")
    page.goto(BASE + "/bulk-transfer-out", wait_until="domcontentloaded")
    page.locator("button", has_text="UPLOAD FILE").first.wait_for(timeout=60_000)
    _wait(page, 1000)
    if (_counts(page).get("all") or 0) > 0:
        _log("Clearing the rows left on the page")
        page.locator("button", has_text="CLEAR UPLOAD").first.click()
        _click_confirm_if_any(page, 3000)
        _wait(page, 1000)
    page.set_input_files("input[type=file]", path)
    _log("File given to LEAP - waiting for it to read the rows")
    last, stable, t0 = None, 0, time.time()
    while time.time() - t0 < 180:
        _wait(page, 1000)
        c = _counts(page)
        if c["all"] and c == last:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
        last = c
    c = _counts(page)
    if not c["all"]:
        raise RuntimeError("LEAP did not show any rows after the upload")
    part.update(c)
    _step(f"upload{i}", status="done", detail=f"{c['all']} rows read by LEAP")
    _step(f"check{i}", status="doing")
    if c["error"]:
        try:
            page.locator("button", has_text=re.compile(r"^\s*ERROR")).first.click()
            _wait(page, 1000)
            part["errors"] = [t.replace("\n", " | ")[:300] for t in
                              page.locator(".ant-table-tbody tr.ant-table-row").all_inner_texts()[:60]]
            page.locator("button", has_text=re.compile(r"^\s*ALL")).first.click()
        except Exception:  # noqa: BLE001
            pass
    ok = c["all"] == expected and c["clean"] == expected and not c["error"]
    msg = f"ALL {c['all']} · CLEAN {c['clean']} · ERROR {c['error']} (our file: {expected} rows)"
    _step(f"check{i}", status="done" if ok else "error", detail=msg)
    _log(msg)

    # ---- wait for the user's OK (the only step that changes anything in LEAP)
    _step(f"submit{i}", status="waiting",
          detail="Check the counts and press Submit to LEAP" if ok else
          "Counts do not match / errors - fix the file, or press Submit anyway if you are sure")
    STATE["phase"] = "waiting"
    STATE["check_ok"] = ok
    STATE["decision"] = None
    _decision.clear()
    _log("Waiting for your OK to submit")
    _snap(force=True)
    t_wait = time.time()
    while not _decision.is_set() and time.time() - t_wait < CONFIRM_WAIT:
        _decision.wait(2)
    if not _decision.is_set():
        STATE["decision"] = "cancel"
        _log("No answer in 30 minutes")
    STATE["phase"] = "running"
    if STATE["decision"] != "submit":
        _step(f"submit{i}", status="skip", detail="Not submitted")
        raise _Stop()

    _step(f"submit{i}", status="doing", detail="Submitting…")
    _log("Pressing SUBMIT in LEAP")
    seen = len(api_log)
    page.locator("button", has_text=re.compile(r"^\s*SUBMIT\s*$")).first.click()
    _click_confirm_if_any(page, 5000)
    note = page.locator(".ant-notification-notice")
    try:
        note.first.wait_for(state="visible", timeout=180_000)
        text = " ".join(note.first.inner_text().split())
    except Exception:  # noqa: BLE001
        text = ""
    api_text = ""
    for r in api_log[seen:]:
        try:
            api_text = f"HTTP {r.status}: " + r.text()[:500]
        except Exception:  # noqa: BLE001
            api_text = f"HTTP {r.status}"
    part["submitted"] = True
    part["message"] = text or api_text or "Submitted"
    bad = re.search(r"\b(error|failed)\b", text, re.I) and not re.search(r"\bsuccess", text, re.I)
    _step(f"submit{i}", status="error" if bad else "done", detail=part["message"][:300])
    _log(f"LEAP says: {part['message'][:300]}")
    if api_text:
        _log(f"LEAP answer: {api_text[:300]}")
    STATE["submit_message"] = part["message"]
    if bad:
        raise RuntimeError(f"LEAP did not accept the file: {text}")


def _wait_job(page):
    _step("job", status="doing", detail="Waiting for LEAP's background job")
    _log("Watching LEAP's Jobs Tracker")
    t0 = time.time()
    text = ""
    page.goto(BASE + "/jobs-tracker", wait_until="domcontentloaded")
    while time.time() - t0 < JOB_WAIT:
        if _cancelled():
            raise _Stop()
        _wait(page, 5000)
        try:
            text = " ".join(page.locator("main").inner_text().split())
        except Exception:  # noqa: BLE001
            text = ""
        busy = re.search(r"PENDING|STARTING|RUNNING|PROCESSING|Calculating|Almost done|Initializing", text, re.I)
        if "No recent background jobs" in text or (text and not busy):
            break
        m = re.search(r"(\d+)\s*/\s*(\d+)", text)
        if m:
            _step("job", detail=f"{m.group(1)} of {m.group(2)} processed")
    done = re.search(r"FAILED", text)
    _step("job", status="error" if done else "done",
          detail="LEAP reported a FAILED job - the check below shows what went through" if done
          else f"Done ({int(time.time() - t0)} s)")
    _log(f"Jobs Tracker: {text[:200]}")


def _download_report(page, out_dir):
    page.goto(BASE + "/reports", wait_until="domcontentloaded")
    page.locator(".ant-select").first.wait_for(timeout=60_000)
    _wait(page, 800)
    page.locator(".ant-select").last.click()
    page.locator(".ant-select-item-option", has_text=re.compile(rf"^\s*{re.escape(REPORT_NAME)}\s*$", re.I)).first.click()
    _wait(page, 500)
    with page.expect_download(timeout=180_000) as dl:
        page.locator("button", has_text="Download Report").first.click()
    d = dl.value
    path = os.path.join(out_dir, f"{datetime.now():%Y%m%d_%H%M%S}_{d.suggested_filename}")
    d.save_as(path)
    return path


def _verify(page, run, run_rows, out_dir):
    res = None
    for attempt in range(1, VERIFY_TRIES + 1):
        if _cancelled():
            raise _Stop()
        _step("report", status="doing", detail=f"Downloading (try {attempt})")
        path = _download_report(page, out_dir)
        with open(path, "rb") as fh:
            rep = parse_pending_csv(fh.read())
        _step("report", status="done", detail=f"{os.path.basename(path)} · {len(rep)} lines")
        _log(f"Report downloaded: {os.path.basename(path)} ({len(rep)} lines)")
        _step("verify", status="doing")
        res = reconcile(run_rows, rep)
        res["report_file"] = os.path.basename(path)
        res["checked_at"] = datetime.now().isoformat(timespec="seconds")
        if not res["missing"] or STATE["mode"] != "upload" or attempt == VERIFY_TRIES:
            break
        _step("verify", detail=f"{res['missing']} invoice(s) not in the report yet - checking again in {VERIFY_GAP} s")
        _log(f"{res['missing']} not in the report yet - LEAP may still be processing")
        _wait(page, VERIFY_GAP * 1000)
    status = "verified" if not (res["missing"] or res["short"] or res["extra"]) else "problems"
    detail = (f"All {res['confirmed']} invoices confirmed" if status == "verified" else
              f"{res['confirmed']} confirmed · {res['missing']} missing · {res['short']} short · {res['extra']} extra")
    _step("verify", status="done" if status == "verified" else "error", detail=detail)
    _log(detail)
    if res["missing"]:
        STATE["retry_run_id"] = _make_retry(run, run_rows, res)
        res["retry_run_id"] = STATE["retry_run_id"]
    STATE["verify"] = res
    _save_status(run["id"], status, res)


def _make_retry(run, run_rows, res):
    """A History file with only the missing invoices. Not made again for a file that is itself a
    retry, nor when this file already has a retry with the same invoices."""
    from datetime import date as _date
    from .store import active_template, package
    rows = problem_rows(run_rows, res)
    if not rows:
        return None
    me = one("SELECT summary, leap_result FROM chep_runs WHERE id=?", (run["id"],)) or {}
    if json.loads(me.get("summary") or "{}").get("retry_of"):
        _log("This file is already a retry file - download it from History to upload again")
        return None
    prev = json.loads(me.get("leap_result") or "{}").get("retry_run_id")
    if prev:
        old = one("SELECT id, rows FROM chep_runs WHERE id=?", (prev,))
        if old and {(r["customer"], r["invoice"]) for r in json.loads(old["rows"] or "[]")} == \
                {(r["customer"], r["invoice"]) for r in rows}:
            return prev
    _, tdata, _ = active_template()
    tpl_rows = [dict(r, doc_date=_date.fromisoformat(r["doc_date"]) if r.get("doc_date") else None) for r in rows]
    stem = re.sub(r"\.(xlsx|zip)$", "", run["file_name"], flags=re.I)
    stem = re.sub(r" \(\d+ files\)$", "", stem)
    n_inv = len({(r["customer"], r["invoice"]) for r in rows})
    fname, data = package(tdata, tpl_rows, f"{stem} retry ({n_inv} invoices).xlsx")
    con = get_db()
    cur = con.execute("INSERT INTO chep_runs(batch_id, created_at, file_name, doc_date, summary, rows, xlsx) "
                      "VALUES(?,?,?,?,?,?,?)",
                      (run["batch_id"], datetime.now().isoformat(timespec="seconds"), fname,
                       max((r.get("doc_date") or "") for r in rows) or None,
                       json.dumps(dict(source=f"Retry of {run['file_name']}", sheets=[], rows=len(rows),
                                       invoices=n_inv, cheps=sum(r["qty"] for r in rows) / 2, retry_of=run["id"])),
                       json.dumps(rows), data))
    con.commit()
    _log(f"Retry file made in History: {fname}")
    return cur.lastrowid


def _save_status(run_id, status, result):
    con = get_db()
    con.execute("UPDATE chep_runs SET leap_status=?, leap_result=?, leap_at=? WHERE id=?",
                (status, json.dumps(result, default=str), datetime.now().isoformat(timespec="seconds"), run_id))
    con.commit()
