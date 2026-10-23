"""TAFE payments straight from TAFE Channel - no file to download by hand.

What a person does (screen recording of 22-Oct-2026):
    Account Info > Payment Details  (/meta/default/wm_xt_fabricfolder/0000012967)
    From Date, To Date, Company = TAFE, Inv/Bill No. empty  ->  Fetch  ->  Excel icon
    -> PaymentDetailsExport<ddmmyyyyhhmmss>.xls  'Payment Clearance Details for Vendor DS1615 from .. to ..'
We send the same requests without a browser (the same way as Fetch GRIN and the DQMS report) and load the .xls
with the same reader as a manual upload. One month per request. Works on the PC and on the website; the website
hands it to the SDEW PC when TAFE Channel does not answer it (pc_jobs kind 'pay_fetch').
When the portal answers something unexpected, its pages are saved in data/grin_http_debug/ to check by hand.
"""
import html
import os
import re
import threading
import traceback
import urllib.parse
from datetime import date, datetime, timedelta

from ... import config
from ...supp.services import grin_http as gh

PAGE = "/meta/default/wm_xt_fabricfolder/0000012967"
STATUS = dict(running=False, log=[], started="", finished="", error="", result=None)
_lock = threading.Lock()


def _log(msg):
    STATUS["log"].append(f"{datetime.now():%H:%M:%S}  {msg}")
    STATUS["log"] = STATUS["log"][-60:]
    print("[Payments]", msg)


def months(d1, d2):
    d = d1
    while d <= d2:
        nxt = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield d, min(d2, nxt - timedelta(days=1))
        d = nxt


def _pay_form(page):
    """The form with the Company list (has a TAFE option) and two date boxes."""
    for f in gh._forms(page):
        if any("TAFE" in opts for opts in f["selects"].values()) and \
                sum(1 for n, t, *_ in f["inputs"] if n.endswith("__date") or "date" in n.lower()) >= 2:
            return f
    return None


def _fields(form, d1, d2, button_id):
    dates = [n for n, t, *_ in form["inputs"] if n.endswith("__date")] or \
            [n for n, t, *_ in form["inputs"] if "date" in n.lower() and t in ("text", "")]
    frm, to = (dates + [None, None])[:2]
    out = []
    for name, typ, value, checked in form["inputs"]:
        if typ in ("submit", "button", "image", "reset", "file") or name == "__fc":
            continue
        if typ in ("checkbox", "radio") and not checked:
            continue
        if name == frm:
            value = d1.strftime("%d/%m/%Y")
        elif name == to:
            value = d2.strftime("%d/%m/%Y")
        out.append((name, value))
    for name, opts in form["selects"].items():
        out.append((name, "TAFE" if "TAFE" in opts else form["selected"].get(name, opts[0] if opts else "")))
    out.append(("__fc", button_id if ":" in button_id else f"{form['id']}:{button_id}"))
    return out


def _button(page, form, words):
    """id of a button / link whose value, id or title has one of the words (Fetch, excel ...)."""
    for name, typ, value, _ in form["inputs"]:
        if typ in ("submit", "button", "image") and any(w in (value + name).lower() for w in words):
            return name
    for m in re.finditer(r'<(?:a|input|button|img)\b[^>]*\bid="([^"]+)"[^>]*>', page, re.I):
        tag = m.group(0).lower()
        if any(w in tag for w in words):
            return m.group(1)
    return None


def fetch_period(s, d1, d2):
    """-> (file name, xls bytes) or None when TAFE has no payment in the period."""
    try:
        url, _, body = s.get(PAGE)
        page = gh._text(body)
        form = _pay_form(page)
        if not form:
            raise gh.PortalError(f"Payment Details page not found - saved as {gh._debug('pay_page', body)}")
        fetch_btn = _button(page, form, ("fetch",)) or "button1"
        act = urllib.parse.urljoin(url, html.unescape(form["action"]) or url)
        url2, _, body2 = s.post(act, _fields(form, d1, d2, fetch_btn), referer=url)
        page2 = gh._text(body2)
        form2 = _pay_form(page2)
        if not form2:
            raise gh.PortalError(f"Fetch did not return the Payment Details page - saved as {gh._debug('pay_after_fetch', body2)}")
        if "Payment Clearance Details" not in page2 and re.search(r"no\s+(records|data|rows)", page2, re.I):
            return None
        exp = _button(page2, form2, ("excel", "xls", "export"))
        if not exp:
            if "Payment Clearance Details" not in page2:
                return None
            raise gh.PortalError(f"Excel button not found - saved as {gh._debug('pay_after_fetch', body2)}")
        act2 = urllib.parse.urljoin(url2, html.unescape(form2["action"]) or url2)
        _, headers, data = s.post(act2, _fields(form2, d1, d2, exp), referer=url2)
    except gh.PortalError:
        raise
    except Exception as e:  # noqa: BLE001
        raise gh.PortalError(gh._net_msg(e))
    if data[:4] != b"\xd0\xcf\x11\xe0" and data[:2] != b"PK":
        raise gh.PortalError(f"Export did not return an Excel file ({headers.get('Content-Type', '?')}) - "
                             f"saved as {gh._debug('pay_after_export', data)}")
    cd = headers.get("Content-Disposition") or ""
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', cd)
    name = urllib.parse.unquote(m.group(1)) if m else f"PaymentDetailsExport_{d1:%Y%m%d}_{d2:%Y%m%d}.xls"
    return name, data


def run(d1, d2):
    """Synchronous: fetch every month and load it. Fills STATUS."""
    from .ingest import _save, store_payments
    from . import status as st
    STATUS.update(running=True, log=[], started=datetime.now().isoformat(timespec="seconds"), finished="",
                  error="", result=None)
    total = 0
    try:
        _log("Logging in to TAFE Channel - Account Info > Payment Details, Company TAFE")
        s = gh.login(config.read_env())
        for a, b in months(d1, d2):
            got = fetch_period(s, a, b)
            if not got:
                _log(f"{a:%d/%m/%Y} - {b:%d/%m/%Y}: no payments")
                continue
            name, data = got
            stored, path = _save(name, data)
            res = store_payments(name, stored, path)
            total += res.get("rows", 0)
            _log(f"{a:%d/%m/%Y} - {b:%d/%m/%Y}: {res['message']}")
        STATUS["result"] = dict(lines=total)
        _log("Done")
    except gh.PortalError as e:
        STATUS["error"] = str(e)
        _log(f"Stopped: {e}")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        STATUS["error"] = str(e)
        _log(f"Stopped: {e}")
    finally:
        STATUS["running"] = False
        STATUS["finished"] = datetime.now().isoformat(timespec="seconds")
        st.invalidate()
    return STATUS


def start(d1, d2, headed=False):
    """Same shape as grin_portal.start (used by the PC job runner)."""
    with _lock:
        if STATUS["running"]:
            return False
    run(d1, d2)
    return True


def network_problem(msg):
    m = (msg or "").lower()
    return "did not answer" in m or "could not reach" in m or "timed out" in m


def default_dates():
    d2 = date.today()
    return d2 - timedelta(days=45), d2
