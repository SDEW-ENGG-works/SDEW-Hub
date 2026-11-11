"""Pulls 'GRIN Details' from TAFE Channel (wb01.tafechannel.com) like a person would:
log in, open Grin Details report, Company Code TAFE, one month at a time (TAFE allows max 31 days),
Fetch, Export as Excel -> the same GRIN importer as a manual upload.

Needs:  pip install playwright   +   python -m playwright install chromium
        TAFE_USER / TAFE_PASS in the .env file next to server.py
Element ids were checked on the live portal on 10-Oct-2026.
"""
import os
import threading
import time
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
# Live view (like LEAP): the newest screenshot of the TAFE page as JPEG. The GRIN page shows it to whoever
# is looking - on the PC, or on the website when the PC does the fetch (pc_jobs copies it to grin_shots).
SHOT = {"ts": 0.0, "jpg": None, "seq": 0}
_PAGE = {"page": None, "thread": None}


def _snap(force=False):
    """Screenshot for the live view - only from the browser's own thread, at most one a second."""
    page = _PAGE["page"]
    if page is None or threading.current_thread() is not _PAGE["thread"]:
        return
    now = time.time()
    if not force and now - SHOT["ts"] < 1.0:
        return
    try:
        SHOT["jpg"] = page.screenshot(type="jpeg", quality=55)
        SHOT["ts"] = now
        SHOT["seq"] += 1
    except Exception:  # noqa: BLE001 - page busy / navigating: next time
        pass


def _wait_visible(page, selector, timeout_ms):
    """Like locator.wait_for(state='visible') but keeps the live view fresh while waiting."""
    end = time.time() + timeout_ms / 1000.0
    loc = page.locator(selector)
    while time.time() < end:
        try:
            if loc.count() and loc.first.is_visible():
                return True
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(700)
        _snap()
    return False


def _log(msg):
    STATUS["log"].append(f"{datetime.now():%H:%M:%S}  {msg}")
    STATUS["log"] = STATUS["log"][-60:]
    print("[GRIN sync]", msg)


def record_fetch(d1, d2):
    """A fetch that finished without error: remember when, and that TAFE Channel was checked up to d2 -
    so 'GRIN dates ... to' and 'Last fetched' move on even when the period had no new GRIN."""
    from ...db import get_setting, set_setting
    try:
        old = get_setting("grin.fetched") or {}
        to = min(d2, date.today()).isoformat()
        set_setting("grin.fetched", dict(at=datetime.now().isoformat(timespec="seconds"), first=d1.isoformat(), to=to,
                                         checked_to=max(to, old.get("checked_to") or "")))
        from ...grin.services import status as gst
        gst.invalidate()                       # the GRIN status uses "checked up to" - work it out again
    except Exception:  # noqa: BLE001 - never fail the fetch for this
        traceback.print_exc()


def fetched():
    """{'at': last successful fetch, 'checked_to': TAFE Channel checked up to this date} (empty before the first)."""
    from ...db import get_setting
    try:
        return get_setting("grin.fetched") or {}
    except Exception:  # noqa: BLE001
        return {}


def covered_until(last_grin_date):
    """GRIN data is complete up to: the newest GRIN date, or later when a fetch checked further and found none."""
    return max(last_grin_date or "", fetched().get("checked_to") or "") or None


def last_fetched(updated_at):
    return max(updated_at or "", fetched().get("at") or "") or None


def months(start, end):
    d = start
    while d <= end:
        nxt = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield d, min(end, nxt - timedelta(days=1))
        d = nxt


def browser_available():
    """Playwright + Chromium on this PC. Never on Vercel (too big for a function)."""
    if config.ON_VERCEL:
        return False
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def available():
    """Fetch GRIN always works: with the browser on the PC, without it (plain web requests) elsewhere."""
    return True


def method():
    m = (config.read_env().get("GRIN_FETCH") or os.environ.get("GRIN_FETCH") or "auto").lower()
    if m == "http" or not browser_available():
        return "http"
    return "browser"


def start(d1, d2, headed=False, window=None):
    """Starts the fetch. On Vercel it runs to the end inside this request (a function cannot keep a thread
    running after it answered) - STATUS then already holds the result."""
    with _lock:
        if STATUS["running"]:
            return False
        STATUS.update(running=True, log=[], started=datetime.now().isoformat(timespec="seconds"), finished="", error="")
        SHOT.update(ts=0.0, jpg=None)
    # "Show the browser" ticked: always the real browser (so it opens on this PC's screen), even if
    # GRIN_FETCH=http is set - as long as Playwright is installed here
    use_browser = method() == "browser" or (headed and browser_available())
    target = _run if use_browser else _run_http
    if headed and not use_browser:
        _log("The website cannot show a browser - start the hub on the SDEW PC (start.bat) to see it. Fetching without it"
             if config.ON_VERCEL else
             "The browser cannot be shown (Playwright is not installed on this computer) - fetching without it")
    # window: open a real browser window on this computer. Default = headed. The website's jobs ask for
    # the live view only (window=False): nobody is sitting at the PC then.
    win = headed if window is None else window
    if config.ON_VERCEL:
        target(d1, d2, win)
    else:
        threading.Thread(target=target, args=(d1, d2, win), daemon=True).start()
    return True


def _run_http(d1, d2, headed=False):
    from .grin_http import PortalError, fetch_month, login
    from .ingest import ingest_grin_file
    try:
        _log("Logging in to TAFE Channel (no browser)")
        s = login(config.read_env())
        out_dir = os.path.join(config.DATA_DIR, "grin_downloads")
        os.makedirs(out_dir, exist_ok=True)
        for a, b in months(d1, d2):
            got = fetch_month(s, a, b)
            if not got:
                _log(f"{a:%d/%m/%Y} - {b:%d/%m/%Y}: no GRIN rows")
                continue
            name, data = got
            path = os.path.join(out_dir, f"{name[:-4]}_{datetime.now():%H%M%S}.xls")
            with open(path, "wb") as fh:
                fh.write(data)
            res = ingest_grin_file(path, os.path.basename(path), source="Portal")
            _log(f"{a:%d/%m/%Y} - {b:%d/%m/%Y}: {res['lines']} lines ({res['added']} new)")
        record_fetch(d1, d2)
        _log("Done")
    except PortalError as e:
        STATUS["error"] = str(e)
        _log(f"Stopped: {e}")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        STATUS["error"] = str(e)
        _log(f"Stopped: {e}")
    finally:
        STATUS["running"] = False
        STATUS["finished"] = datetime.now().isoformat(timespec="seconds")


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
            page = browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 760}).new_page()
            _PAGE.update(page=page, thread=threading.current_thread())
            try:
                _log("Logging in to TAFE Channel")
                page.goto(url + "/", wait_until="domcontentloaded")
                _snap(True)
                if page.locator("#wm_login-password").count():
                    page.fill("#wm_login-username", env["TAFE_USER"])
                    page.fill("#wm_login-password", env["TAFE_PASS"])
                    _snap(True)
                    page.click("#submit_login")
                    page.wait_for_load_state("networkidle")
                    _snap(True)
                    if page.locator("#wm_login-password").count():
                        raise RuntimeError("Login failed - check TAFE_USER / TAFE_PASS in .env")
                for a, b in months(d1, d2):
                    _log(f"{a:%d/%m/%Y} - {b:%d/%m/%Y}: opening GRIN Details")
                    page.goto(url + "/GRINDetails", wait_until="domcontentloaded")
                    page.wait_for_load_state("networkidle")
                    _snap(True)
                    page.locator(FROM_DATE).wait_for(timeout=60_000)
                    page.select_option(COMPANY, value="TAFE")
                    page.wait_for_function(f"document.querySelector('{PLANT}').options.length > 1", timeout=60_000)
                    for sel, val in ((FROM_DATE, a.strftime("%d/%m/%Y")), (TO_DATE, b.strftime("%d/%m/%Y"))):
                        page.click(sel)
                        page.fill(sel, "")
                        page.type(sel, val)
                        page.keyboard.press("Tab")
                    _snap(True)
                    page.click(FETCH)
                    if not _wait_visible(page, EXPORT_XLS, 180_000):
                        if page.locator(RESULTS).count() == 0:
                            _log(f"{a:%d/%m/%Y} - {b:%d/%m/%Y}: no GRIN rows")
                            continue
                        raise PWTimeout("TAFE Channel did not show the Excel button within 3 minutes")
                    _snap(True)
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
                _snap(True)
                _PAGE.update(page=None, thread=None)
                browser.close()
        record_fetch(d1, d2)
        _log("Done")
    except Exception as e:
        traceback.print_exc()
        STATUS["error"] = str(e)
        _log(f"Stopped: {e}")
    finally:
        STATUS["running"] = False
        STATUS["finished"] = datetime.now().isoformat(timespec="seconds")
