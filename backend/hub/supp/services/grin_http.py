"""'GRIN Details' from TAFE Channel WITHOUT a browser (works on Vercel, where Playwright cannot run).

Same idea as the DQMS report fetch (checked live on 21-Oct-2026): the portal page is a webMethods CAF/JSF form,
so we send the requests the page itself sends:
    1. GET  /                      session cookie, then POST the login form
    2. GET  /GRINDetails           the report page (hidden fields: ViewState, form token, ...)
    3. POST the form  + From/To date, Company=TAFE, __fc=<form>:button1               (Fetch)
    4. POST the form  again + __fc=<form>:excelCommandButton                          (Export as Excel) -> .xls
One month per fetch (TAFE allows 31 days). Field names come from the Playwright version (checked 10-Oct-2026).
When the portal answers something unexpected, its pages are saved in data/grin_http_debug/ to check by hand.
"""
import html
import http.cookiejar
import os
import re
import ssl
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser

from .. import config

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
TIMEOUT = 90
FORM = "jsfwmp11990:defaultForm"
FROM_SUFFIX = "dateInput__date"
TO_SUFFIX = "htmlInputText3__date"
COMPANY_SUFFIX = "htmlSelectOneMenu1"


class PortalError(Exception):
    pass


class _Forms(HTMLParser):
    """Every form: id, action, all input (name, type, value) and selects (name -> option values, selected)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms, self.cur, self.sel = [], None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.cur = dict(id=a.get("id", ""), action=a.get("action", ""), inputs=[], selects={}, selected={})
            self.forms.append(self.cur)
        elif self.cur is None:
            return
        elif tag == "input" and a.get("name"):
            self.cur["inputs"].append((a["name"], (a.get("type") or "text").lower(), a.get("value") or "",
                                       "checked" in a))
        elif tag == "select" and a.get("name"):
            self.sel = a["name"]
            self.cur["selects"][self.sel] = []
        elif tag == "option" and self.sel:
            v = a.get("value") or ""
            self.cur["selects"][self.sel].append(v)
            if "selected" in a:
                self.cur["selected"][self.sel] = v

    def handle_endtag(self, tag):
        if tag == "select":
            self.sel = None
        elif tag == "form":
            self.cur = None


def _forms(page):
    p = _Forms()
    p.feed(page)
    return p.forms


def _login_needed(page):
    return any(t == "password" for f in _forms(page) for _, t, _, _ in f["inputs"])


def _grin_form(page):
    for f in _forms(page):
        if any(n.endswith(FROM_SUFFIX) for n, *_ in f["inputs"]):
            return f
    return None


class _Session:
    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar),
                                              urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        self.op.addheaders = [("User-Agent", UA), ("Accept-Language", "en-IN,en;q=0.9")]

    def get(self, url):
        with self.op.open(urllib.parse.urljoin(self.base + "/", url), timeout=TIMEOUT) as r:
            return r.geturl(), r.headers, r.read()

    def post(self, url, fields, referer=None):
        req = urllib.request.Request(urllib.parse.urljoin(self.base + "/", url),
                                     data=urllib.parse.urlencode(fields).encode(), method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        if referer:
            req.add_header("Referer", referer)
        with self.op.open(req, timeout=TIMEOUT) as r:
            return r.geturl(), r.headers, r.read()


def _text(b):
    return b.decode("utf-8", errors="replace")


def _debug(name, body):
    d = os.path.join(config.DATA_DIR, "grin_http_debug")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{datetime.now():%Y%m%d_%H%M%S}_{name}.html")
    with open(p, "wb") as fh:
        fh.write(body if isinstance(body, bytes) else body.encode("utf-8", "replace"))
    return p


def _fields(form, d1, d2, button):
    """All the form's fields as the browser would send them, with our dates / company and the pressed button."""
    out = []
    for name, typ, value, checked in form["inputs"]:
        if typ in ("submit", "button", "image", "reset", "file") or name == "__fc":
            continue
        if typ in ("checkbox", "radio") and not checked:
            continue
        if name.endswith(FROM_SUFFIX):
            value = d1.strftime("%d/%m/%Y")
        elif name.endswith(TO_SUFFIX):
            value = d2.strftime("%d/%m/%Y")
        out.append((name, value))
    for name, opts in form["selects"].items():
        if name.endswith(COMPANY_SUFFIX):
            out.append((name, "TAFE" if "TAFE" in opts else form["selected"].get(name, opts[0] if opts else "")))
        else:
            out.append((name, form["selected"].get(name, opts[0] if opts else "")))
    out.append(("__fc", f"{form['id'] or FORM}:{button}"))
    return out


def login(env):
    base = (env.get("TAFE_URL") or "https://wb01.tafechannel.com").rstrip("/")
    if not env.get("TAFE_USER") or not env.get("TAFE_PASS"):
        where = "Vercel > Settings > Environment Variables" if config.ON_VERCEL else "the .env file next to server.py"
        raise PortalError(f"Put TAFE_USER and TAFE_PASS in {where}")
    s = _Session(base)
    try:
        url, _, body = s.get("/")
    except Exception as e:  # noqa: BLE001
        raise PortalError(_net_msg(e))
    page = _text(body)
    if _login_needed(page):
        lf = next((f for f in _forms(page) if any(t == "password" for _, t, _, _ in f["inputs"])), None)
        action = html.unescape(lf["action"]) if lf and lf["action"] else "/user.current.start.page"
        fields = [(n, v) for n, t, v, _ in (lf["inputs"] if lf else []) if t == "hidden"]
        fields += [("username", env["TAFE_USER"]), ("password", env["TAFE_PASS"]), ("submit_login", "Log In")]
        url, _, body = s.post(urllib.parse.urljoin(url, action), fields, referer=url)
        if _login_needed(_text(body)):
            raise PortalError("TAFE Channel login failed - check TAFE_USER / TAFE_PASS")
    return s


def _net_msg(e):
    msg = str(e)
    if config.ON_VERCEL and ("timed out" in msg.lower() or "errno 110" in msg.lower()):
        return ("TAFE Channel did not answer the website's server. It only accepts connections from India - "
                "check that vercel.json has \"regions\": [\"bom1\"], or press Fetch GRIN on the SDEW PC.")
    return f"Could not reach TAFE Channel: {e}"


def fetch_month(s, d1, d2):
    """-> (file name, xls bytes) or None when TAFE has no GRIN in the period."""
    try:
        url, _, body = s.get("/GRINDetails")
        form = _grin_form(_text(body))
        if not form:
            raise PortalError(f"GRIN Details page not found - saved as {_debug('grin_page', body)}")
        act = urllib.parse.urljoin(url, html.unescape(form["action"]) or url)
        url2, _, body2 = s.post(act, _fields(form, d1, d2, "button1"), referer=url)
        page2 = _text(body2)
        form2 = _grin_form(page2)
        if not form2:
            raise PortalError(f"Fetch did not return the GRIN page - saved as {_debug('after_fetch', body2)}")
        if "excelCommandButton" not in page2:
            if re.search(r"no\s+(records|data|rows)", page2, re.I) or "asyncTable" not in page2:
                return None
        act2 = urllib.parse.urljoin(url2, html.unescape(form2["action"]) or url2)
        _, headers, data = s.post(act2, _fields(form2, d1, d2, "excelCommandButton"), referer=url2)
    except PortalError:
        raise
    except Exception as e:  # noqa: BLE001
        raise PortalError(_net_msg(e))
    if data[:4] != b"\xd0\xcf\x11\xe0" and data[:2] != b"PK":
        raise PortalError(f"Export as Excel did not return a file ({headers.get('Content-Type', '?')}) - "
                          f"saved as {_debug('after_export', data)}")
    return f"GRIN_{d1:%Y%m%d}_{d2:%Y%m%d}.xls", data
