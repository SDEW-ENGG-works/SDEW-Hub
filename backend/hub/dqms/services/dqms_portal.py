"""Gets the DQMS Batch Details Report from TAFE Channel (wb01.tafechannel.com) like a person would:

    log in  ->  ASN > Batch Details Report (DQMS)  ->  Part Number = ALL  ->  Fetch  ->  Export as Excel

and feeds the downloaded .xls to the same reader as a manual upload.
Same login code as the Supplementary Bill app's "Fetch GRIN".

Needs (PC only - Vercel cannot run a browser):
    pip install playwright
    python -m playwright install chromium
    TAFE_USER / TAFE_PASS (and optionally TAFE_URL, DQMS_REPORT_URL) in the .env file next to server.py
"""
import os
import threading
import traceback
from datetime import datetime

from .. import config

# Batch Details Report (DQMS) page, from the address bar on 19-Oct-2026
DEFAULT_REPORT_PATH = "/meta/default/wm_xt_fabricfolder/0003064229"

PART_SELECT = "select:has(option:text-is('ALL'))"
FETCH_BTN = "input[value='Fetch'], button:has-text('Fetch'), a:has-text('Fetch')"
EXPORT_XLS = "[id$='excelCommandButton'], a:has-text('Export as Excel'), input[value='Export as Excel']"

STATUS = dict(running=False, log=[], started="", finished="", error="", result=None)
_lock = threading.Lock()


def _log(msg):
    STATUS["log"].append(f"{datetime.now():%H:%M:%S}  {msg}")
    STATUS["log"] = STATUS["log"][-40:]
    print("[DQMS fetch]", msg)


def available():
    if config.ON_VERCEL:
        return False
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def why_not():
    if config.ON_VERCEL:
        return "The online (Vercel) site cannot open a browser - use the app on the PC for this button."
    if not available():
        return "Playwright is not installed on this PC: pip install playwright  then  python -m playwright install chromium"
    env = config.read_env()
    if not env.get("TAFE_USER") or not env.get("TAFE_PASS"):
        return "Put TAFE_USER and TAFE_PASS in the .env file next to server.py"
    return ""


def start(headed=False):
    with _lock:
        if STATUS["running"]:
            return False
        STATUS.update(running=True, log=[], started=datetime.now().isoformat(timespec="seconds"),
                      finished="", error="", result=None)
    threading.Thread(target=_run, args=(headed,), daemon=True).start()
    return True


def _run(headed):
    from . import store
    env = config.read_env()
    url = env.get("TAFE_URL", "https://wb01.tafechannel.com").rstrip("/")
    report_url = env.get("DQMS_REPORT_URL") or (url + DEFAULT_REPORT_PATH)
    try:
        problem = why_not()
        if problem:
            raise RuntimeError(problem)
        from playwright.sync_api import sync_playwright
        out_dir = os.path.join(config.DATA_DIR, "dqms_downloads")
        os.makedirs(out_dir, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not headed)
            page = browser.new_context(accept_downloads=True).new_page()
            page.set_default_timeout(60_000)
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
                _log("Opening Batch Details Report (DQMS)")
                page.goto(report_url, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle")
                sel = page.locator(PART_SELECT).first
                sel.wait_for()
                sel.select_option(label="ALL")
                _log("Part Number = ALL, Fetch")
                page.locator(FETCH_BTN).first.click()
                exp = page.locator(EXPORT_XLS).first
                exp.wait_for(state="visible", timeout=180_000)
                _log("Export as Excel")
                with page.expect_download(timeout=300_000) as dl:
                    exp.click()
                name = dl.value.suggested_filename or f"DQMSBatchDetailsReport{datetime.now():%d%m%Y%H%M%S}.xls"
                path = os.path.join(out_dir, name)
                dl.value.save_as(path)
                with open(path, "rb") as fh:
                    res = store.ingest(name, fh.read())
                STATUS["result"] = res
                _log(f"{name}: {res.get('batches')} batches of {res.get('parts')} parts loaded")
            except Exception:
                shot = os.path.join(config.DATA_DIR, f"dqms_fetch_error_{datetime.now():%Y%m%d_%H%M%S}.png")
                try:
                    page.screenshot(path=shot, full_page=True)
                    _log(f"Screenshot saved: {shot}")
                except Exception:  # noqa: BLE001
                    pass
                raise
            finally:
                browser.close()
        _log("Done")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        STATUS["error"] = getattr(e, "message", None) or str(e)
        _log(f"Stopped: {STATUS['error']}")
    finally:
        STATUS["running"] = False
        STATUS["finished"] = datetime.now().isoformat(timespec="seconds")
