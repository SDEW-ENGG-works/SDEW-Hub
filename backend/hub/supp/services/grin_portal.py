"""Pulls 'GRIN Details' from TAFE Channel (wb01.tafechannel.com) like a person would:
log in, open Grin Details report, Company Code TAFE, one month at a time (TAFE allows max 31 days),
Fetch, Export as Excel -> the same GRIN importer as a manual upload.

Needs:  pip install playwright   +   python -m playwright install chromium
        TAFE_USER / TAFE_PASS in the .env file next to server.py
Element ids were checked on the live portal on 10-Oct-2026.
"""
import os
import threading
import traceback
from datetime import date, datetime, timedelta

from .. import config

F = "jsfwmp11990:defaultForm:"
FROM_DATE = f'[id="{F}dateInput__date"]'
TO_DATE = f'[id="{F}htmlInputText3__date"]'
COMPANY = f'[id="{F}disjointForm:htmlSelectOneMenu1"]'
PLANT = f'[id="{F}disjointForm:htmlInputText4"]'
FETCH = f'[id="{F}button1"]'
EXPORT_XLS = f'[id="{F}excelCommandButton"]'
RESULTS = f'[id="{F}asyncTable"]'

STATUS = dict(running=False, log=[], started="", finished="", error="")
_lock = threading.Lock()


def _log(msg):
    STATUS["log"].append(f"{datetime.now():%H:%M:%S}  {msg}")
    STATUS["log"] = STATUS["log"][-60:]
    print("[GRIN sync]", msg)


def months(start, end):
    d = start
    while d <= end:
        nxt = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield d, min(end, nxt - timedelta(days=1))
        d = nxt


def available():
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def start(d1, d2, headed=False):
    with _lock:
        if STATUS["running"]:
            return False
        STATUS.update(running=True, log=[], started=datetime.now().isoformat(timespec="seconds"), finished="", error="")
    threading.Thread(target=_run, args=(d1, d2, headed), daemon=True).start()
    return True


def _run(d1, d2, headed):
    from .ingest import ingest_grin_file
    env = config.read_env()
    url = env.get("TAFE_URL", "https://wb01.tafechannel.com/").rstrip("/")
    try:
        if not env.get("TAFE_USER") or not env.get("TAFE_PASS"):
            raise RuntimeError("Put TAFE_USER and TAFE_PASS in the .env file next to server.py")
        from playwright.sync_api import TimeoutError as PWTimeout
        from playwright.sync_api import sync_playwright
        out_dir = os.path.join(config.DATA_DIR, "grin_downloads")
        os.makedirs(out_dir, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not headed)
            page = browser.new_context(accept_downloads=True).new_page()
            try:
                _log("Logging in to TAFE Channel")
                page.goto(url + "/", wait_until="domcontentloaded")
                if page.locator("#wm_login-password").count():
                    page.fill("#wm_login-username", env["TAFE_USER"])
                    page.fill("#wm_login-password", env["TAFE_PASS"])
                    page.click("#submit_login")
                    page.wait_for_load_state("networkidle")
                    if page.locator("#wm_login-password").count():
                        raise RuntimeError("Login failed - check TAFE_USER / TAFE_PASS in .env")
                for a, b in months(d1, d2):
                    page.goto(url + "/GRINDetails", wait_until="domcontentloaded")
                    page.wait_for_load_state("networkidle")
                    page.locator(FROM_DATE).wait_for(timeout=60_000)
                    page.select_option(COMPANY, value="TAFE")
                    page.wait_for_function(f"document.querySelector('{PLANT}').options.length > 1", timeout=60_000)
                    for sel, val in ((FROM_DATE, a.strftime("%d/%m/%Y")), (TO_DATE, b.strftime("%d/%m/%Y"))):
                        page.click(sel)
                        page.fill(sel, "")
                        page.type(sel, val)
                        page.keyboard.press("Tab")
                    page.click(FETCH)
                    try:
                        page.locator(EXPORT_XLS).wait_for(state="visible", timeout=180_000)
                    except PWTimeout:
                        if page.locator(RESULTS).count() == 0:
                            _log(f"{a:%d/%m/%Y} - {b:%d/%m/%Y}: no GRIN rows")
                            continue
                        raise
                    with page.expect_download(timeout=300_000) as dl:
                        page.click(EXPORT_XLS)
                    path = os.path.join(out_dir, f"GRIN_{a:%Y%m%d}_{b:%Y%m%d}_{datetime.now():%H%M%S}.xls")
                    dl.value.save_as(path)
                    res = ingest_grin_file(path, os.path.basename(path), source="Portal")
                    _log(f"{a:%d/%m/%Y} - {b:%d/%m/%Y}: {res['lines']} lines ({res['added']} new)")
            except Exception:
                shot = os.path.join(config.DATA_DIR, f"grin_sync_error_{datetime.now():%Y%m%d_%H%M%S}.png")
                try:
                    page.screenshot(path=shot, full_page=True)
                    _log(f"Screenshot saved: {shot}")
                except Exception:
                    pass
                raise
            finally:
                browser.close()
        _log("Done")
    except Exception as e:
        traceback.print_exc()
        STATUS["error"] = str(e)
        _log(f"Stopped: {e}")
    finally:
        STATUS["running"] = False
        STATUS["finished"] = datetime.now().isoformat(timespec="seconds")
