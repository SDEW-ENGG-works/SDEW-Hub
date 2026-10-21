"""(Same code as the DQMS Upload app, 21-Oct-2026.) Gets the DQMS Batch Details Report from TAFE Channel (wb01.tafechannel.com) without a browser,
so it works on the PC and on Vercel alike. It sends the same requests the portal page sends:

    1. GET  /                                   -> session cookie
    2. POST /user.current.start.page            username, password, submit_login   (log in)
    3. GET  /meta/default/wm_xt_fabricfolder/0003064229      Batch Details Report (DQMS) page
    4. POST <form action>  all hidden fields + Part Number=ALL + __fc=<form>:htmlCommandButton    (Fetch)
    5. POST <form action>  same + __fc=<form>:excelCommandButton    (Export as Excel) -> .xls bytes

The page is a webMethods CAF/JSF form: the button that was pressed goes in the "__fc" field, and every
hidden field (ViewState, form token, table state) is sent back as it came. Checked on the live portal
on 21-Oct-2026: Fetch + Export of 805 batches takes under a second.

Needs TAFE_USER / TAFE_PASS in .env on the PC, or as Vercel environment variables.
Optional: TAFE_URL (default https://wb01.tafechannel.com), DQMS_REPORT_URL.
"""
import html
import http.cookiejar
import re
import ssl
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser

from .. import config

DEFAULT_REPORT_PATH = "/meta/default/wm_xt_fabricfolder/0003064229"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
TIMEOUT = 60


class PortalError(Exception):
    pass


def settings():
    env = config.read_env()
    for k in ("TAFE_USER", "TAFE_PASS", "TAFE_URL", "DQMS_REPORT_URL"):
        import os
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def why_not():
    env = settings()
    if not env.get("TAFE_USER") or not env.get("TAFE_PASS"):
        where = "Vercel > Settings > Environment Variables" if config.ON_VERCEL else "the .env file next to server.py"
        return f"Put TAFE_USER and TAFE_PASS in {where}"
    return ""


def available():
    return not why_not()


# ---- tiny HTML form reader -----------------------------------------------------------------
class _Forms(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms, self.cur, self.sel = [], None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.cur = dict(id=a.get("id", ""), action=a.get("action", ""), hidden=[], selects={}, inputs=[])
            self.forms.append(self.cur)
        elif self.cur is None:
            return
        elif tag == "input":
            self.cur["inputs"].append((a.get("name") or "", (a.get("type") or "text").lower()))
            if (a.get("type") or "").lower() == "hidden" and a.get("name"):
                self.cur["hidden"].append((a["name"], a.get("value") or ""))
        elif tag == "select" and a.get("name"):
            self.sel = a["name"]
            self.cur["selects"][self.sel] = []
        elif tag == "option" and self.sel:
            self.cur["selects"][self.sel].append(a.get("value") or "")

    def handle_endtag(self, tag):
        if tag == "select":
            self.sel = None
        elif tag == "form":
            self.cur = None


def _forms(page):
    p = _Forms()
    p.feed(page)
    return p.forms


def _report_form(page):
    for f in _forms(page):
        for name in f["selects"]:
            if name.endswith("htmlSelectOneMenu"):
                return f, name
    return None, None


def _login_needed(page):
    return any(n == "password" and t == "password" for f in _forms(page) for n, t in f["inputs"])


# ---- the run ---------------------------------------------------------------------------------
class _Session:
    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        ctx = ssl.create_default_context()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar),
                                              urllib.request.HTTPSHandler(context=ctx))
        self.op.addheaders = [("User-Agent", UA), ("Accept-Language", "en-IN,en;q=0.9")]

    def get(self, url):
        with self.op.open(urllib.parse.urljoin(self.base + "/", url), timeout=TIMEOUT) as r:
            return r.geturl(), r.headers, r.read()

    def post(self, url, fields, referer=None):
        data = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(urllib.parse.urljoin(self.base + "/", url), data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        if referer:
            req.add_header("Referer", referer)
        with self.op.open(req, timeout=TIMEOUT) as r:
            return r.geturl(), r.headers, r.read()


def _text(b):
    return b.decode("utf-8", errors="replace")


def fetch_report():
    """-> (file_name, xls_bytes). Raises PortalError with a plain message when something is off."""
    problem = why_not()
    if problem:
        raise PortalError(problem)
    env = settings()
    base = (env.get("TAFE_URL") or "https://wb01.tafechannel.com").rstrip("/")
    report_url = env.get("DQMS_REPORT_URL") or (base + DEFAULT_REPORT_PATH)
    s = _Session(base)
    try:
        # 1-2: log in
        url, _, body = s.get("/")
        page = _text(body)
        if _login_needed(page):
            login = next((f for f in _forms(page) if any(n == "password" for n, _ in f["inputs"])), None)
            action = html.unescape(login["action"]) if login and login["action"] else "/user.current.start.page"
            fields = list(login["hidden"]) if login else []
            fields += [("username", env["TAFE_USER"]), ("password", env["TAFE_PASS"]), ("submit_login", "Log In")]
            url, _, body = s.post(urllib.parse.urljoin(url, action), fields, referer=url)
            if _login_needed(_text(body)):
                raise PortalError("TAFE Channel login failed - check TAFE_USER / TAFE_PASS")
        # 3: report page
        url, _, body = s.get(report_url)
        page = _text(body)
        if _login_needed(page):
            raise PortalError("TAFE Channel asked to log in again - check TAFE_USER / TAFE_PASS")
        form, sel = _report_form(page)
        if not form:
            raise PortalError("Batch Details Report (DQMS) page not found - has the portal changed? "
                              "Set DQMS_REPORT_URL to the page's address.")
        if "ALL" not in form["selects"][sel]:
            raise PortalError("Part Number list has no ALL option")

        def press(frm, button, page_url):
            fields = [(k, v) for k, v in frm["hidden"] if k != "__fc"]
            fields = [(k, v) for k, v in fields if k != sel] + [(sel, "ALL"), ("__fc", f"{frm['id']}:{button}")]
            return s.post(urllib.parse.urljoin(page_url, html.unescape(frm["action"])), fields, referer=page_url)

        # 4: Fetch (Part Number = ALL)
        url2, _, body = press(form, "htmlCommandButton", url)
        form2, sel2 = _report_form(_text(body))
        if not form2:
            raise PortalError("Fetch did not return the report page")
        # 5: Export as Excel
        _, headers, data = press(form2, "excelCommandButton", url2)
        if data[:4] != b"\xd0\xcf\x11\xe0" and data[:2] != b"PK":
            raise PortalError("Export as Excel did not return an Excel file "
                              f"({headers.get('Content-Type', '?')}, {len(data)} bytes)")
        cd = headers.get("Content-Disposition") or ""
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', cd)
        name = urllib.parse.unquote(m.group(1)) if m else f"DQMSBatchDetailsReport{datetime.now():%d%m%Y%H%M%S}.xls"
        return name, data
    except PortalError:
        raise
    except Exception as e:  # noqa: BLE001  (network trouble, portal down ...)
        msg = str(e)
        if config.ON_VERCEL and ("timed out" in msg.lower() or "errno 110" in msg.lower()):
            region = __import__("os").environ.get("VERCEL_REGION", "?")
            raise PortalError(f"TAFE Channel did not answer the website's server (Vercel region {region}). "
                              "TAFE Channel only accepts connections from India - the site must run in bom1 "
                              "(Mumbai, see vercel.json). Until then: fetch on the PC app, or download the "
                              "Batch Details Report from TAFE Channel and drop it here.")
        raise PortalError(f"Could not reach TAFE Channel: {e}")


def run():
    """Fetch + load into the app. -> the same dict as a manual upload of the report."""
    from . import store
    name, data = fetch_report()
    res = store.ingest(name, data)
    res["fetched_from_portal"] = True
    return res


# ---- the hub's button: same STATUS shape as Fetch GRIN / Tally (the SDEW PC can run it for the website too) ----
STATUS = dict(running=False, log=[], started="", finished="", error="", result=None)


def _log(msg):
    STATUS["log"].append(f"{datetime.now():%H:%M:%S}  {msg}")
    STATUS["log"] = STATUS["log"][-40:]
    print("[DQMS fetch]", msg)


def network_problem(msg):
    m = (msg or "").lower()
    return "did not answer" in m or "could not reach" in m or "timed out" in m


def start(headed=False):
    """Runs to the end inside the call (under a second on the live portal) -> True."""
    STATUS.update(running=True, log=[], started=datetime.now().isoformat(timespec="seconds"),
                  finished="", error="", result=None)
    try:
        _log("Logging in to TAFE Channel - Batch Details Report (DQMS), Part Number ALL")
        res = run()
        STATUS["result"] = {k: res.get(k) for k in ("batches", "parts", "name", "report_time") if k in res}
        _log(f"Loaded {res.get('batches')} batches of {res.get('parts')} parts")
    except PortalError as e:
        STATUS["error"] = str(e)
        _log(f"Stopped: {e}")
    except Exception as e:  # noqa: BLE001
        STATUS["error"] = str(e)
        _log(f"Stopped: {e}")
    finally:
        STATUS["running"] = False
        STATUS["finished"] = datetime.now().isoformat(timespec="seconds")
    return True
