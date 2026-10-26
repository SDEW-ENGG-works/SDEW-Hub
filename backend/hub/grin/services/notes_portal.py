"""Debit / Credit notes from TAFE Channel - Account Info > Debit Credit Note / Intimation Details.

What a person does (screen recording of 26-Oct-2026):  /DebitCreditNoteDetails, Company TAFE, View = All,
From / To date -> Fetch -> a list of documents; 'View Note / Intimation' or 'Advice' opens each one.
Checked live the same day - what the documents are (legend on the page):
    KE / KF / KD / KU / KO / KQ   DR intimation   MDUR / DDBR / SEMB / TGD / SBU / transport  - mostly RATE DIFFERENCE:
                                  TAFE paid the PO rate, we billed more -> per invoice + part: bill rate, PO rate, diff
    KG                            DR intimation HO - CASH DISCOUNT for early payment, per invoice (amount, days, CD)
    ZK / ZL                       TAX INVOICE raised on us - REJECTIONS scrapped on vendor account: part, qty, value,
                                  our invoice (Reference No.) and the rejection document
    KJ / KI / KK / KL / KV        CR intimation - money TAFE gives back
We send the same requests without a browser (like Fetch GRIN / payments):
    1. POST the form (Fetch) with the dates, View = ALL and the table size raised so every row comes in one page
    2. POST the form again with the Excel button -> .xls with Debit / Credit Amount, Plant Code, Reason per document
    3. for every document: the same AJAX call the 'View Note' / 'Advice' link makes -> the note itself (parsed in notes.py)
One month per list (TAFE refuses a longer list). Details are only fetched once per document.
"""
import html
import re
import threading
import time
import traceback
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from ... import config
from ...supp.services import grin_http as gh
from . import notes

PAGE = "/DebitCreditNoteDetails"
STATUS = dict(running=False, log=[], started="", finished="", error="", result=None, more=False)
_lock = threading.Lock()


def _log(msg):
    STATUS["log"].append(f"{datetime.now():%H:%M:%S}  {msg}")
    STATUS["log"] = STATUS["log"][-80:]
    print("[Debit notes]", msg)


def months(d1, d2):
    d = d1
    while d <= d2:
        nxt = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield d, min(d2, nxt - timedelta(days=1))
        d = nxt


def _form(page):
    for f in gh._forms(page):
        if any("viewRadioOption" in n for n, *_ in f["inputs"]):
            return f
    return None


def _values(form):
    out = {}
    order = []
    for name, typ, value, checked in form["inputs"]:
        if typ in ("submit", "button", "image", "reset", "file") or not name:
            continue
        if typ in ("checkbox", "radio") and not checked:
            continue
        if name not in out:
            order.append(name)
        out[name] = value
    for name, opts in form["selects"].items():
        if name not in out:
            order.append(name)
        out[name] = "TAFE" if "TAFE" in opts else form["selected"].get(name, opts[0] if opts else "")
    return out, order


def _encode(vals, order, extra):
    keys = order + [k for k in extra if k not in vals]
    merged = dict(vals, **extra)
    return [(k, merged[k]) for k in keys if k in merged]


class _Page:
    """The Debit Credit Note page after Fetch for one period: rows + what is needed for the detail calls."""

    def __init__(self, s, d1, d2):
        self.s = s
        url, _, body = s.get(PAGE)
        page = gh._text(body)
        form = _form(page)
        if not form:
            raise gh.PortalError(f"Debit Credit Note page not found - saved as {gh._debug('dcn_page', body)}")
        self.F = form["id"] or "jsfwmp12125:defaultForm"
        self.prefix = self.F.split(":")[0]
        vals, order = _values(form)
        for n in list(vals):
            if n.endswith("viewRadioOption"):
                vals[n] = "ALL"
            elif n.endswith("__date"):
                pass
            elif n.endswith("asyncTableVendorDebit__rows"):
                vals[n] = "3000"
        dates = [n for n in order if n.endswith("__date")]
        if len(dates) >= 2:
            vals[dates[0]], vals[dates[1]] = d1.strftime("%d/%m/%Y"), d2.strftime("%d/%m/%Y")
        vals[f"{self.F}:asyncTableVendorDebit__rows"] = "3000"
        if f"{self.F}:asyncTableVendorDebit__rows" not in order:
            order.append(f"{self.F}:asyncTableVendorDebit__rows")
        self.action = urllib.parse.urljoin(url, html.unescape(form["action"]) or url)
        self.url = url
        self.vals, self.order = vals, order
        self._pager()
        # Fetch = the same AJAX call the page makes (a full-page post also lists, but then TAFE's 'Advice' of a
        # rejection comes back empty - checked live 26-Oct-2026)
        p = self.prefix
        text = self._ajax({"__fc": f"{self.F}:button", "__forms": self.F, f"{p}:javax.faces.source": f"{self.F}:button",
                           f"{p}:javax.faces.partial.execute": f"{self.F}:button {self.F}",
                           f"{p}:javax.faces.partial.render": self.F, f"{p}:javax.faces.partial.ajax": "true",
                           f"{p}:javax.faces.behavior.event": "action"})
        m = re.search(r'<update id="%s"><!\[CDATA\[(.*?)\]\]></update>' % re.escape(self.F), text, re.S)
        if not m:
            raise gh.PortalError(f"Fetch did not return the Debit Credit Note list - saved as "
                                 f"{gh._debug('dcn_after_fetch', text)}")
        self.page = m.group(1)
        self.vendor = (re.search(r"for Vendor\s+(\w+)", self.page) or [None, ""])[1]
        self.rows = notes.parse_list(self.page)

    def _pager(self):
        """The tables' pager fields are written by the page's JavaScript - send them like the browser does."""
        for t, rows_ in (("asyncTableVendorDebit", "3000"), ("asyncTable", "10")):
            for k, v in (("__first", "0"), ("__rows", rows_), ("__firstByID", "")):
                name = f"{self.F}:{t}{k}"
                if name not in self.vals:
                    self.order.append(name)
                self.vals[name] = v

    def _ajax(self, extra):
        req = urllib.request.Request(self.action, data=urllib.parse.urlencode(_encode(self.vals, self.order, extra)).encode(),
                                     method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
        req.add_header("Faces-Request", "partial/ajax")
        req.add_header("X-Requested-With", "XMLHttpRequest")
        req.add_header("Referer", self.url)
        with self.s.op.open(req, timeout=gh.TIMEOUT) as r:
            text = gh._text(r.read())
        vs = re.search(r'<update id="[^"]*javax\.faces\.ViewState[^"]*"><!\[CDATA\[(.*?)\]\]>', text, re.S)
        if vs:
            for k in self.vals:
                if k.endswith("javax.faces.ViewState"):
                    self.vals[k] = vs.group(1)
        return text

    def excel(self):
        btn = f"{self.F}:excelCommandButton"
        _, headers, data = self.s.post(self.action, _encode(self.vals, self.order, {"__fc": btn}), referer=self.url)
        if data[:4] != b"\xd0\xcf\x11\xe0" and data[:2] != b"PK":
            return None
        return data

    def detail(self, row):
        """The AJAX call of the row's link -> HTML of the note (modal dialog)."""
        F, rid = self.F, row["rid"]
        advice = (row.get("doc_type") or "").startswith("Z") or f"__row{rid}:link\"" in self.page
        ctl = f"{F}:asyncTableVendorDebit:__row{rid}:" + ("link" if advice else "selectRowIndividualCheckbox")
        p = self.prefix
        extra = {"__fc": ctl, "__forms": F, f"{p}:javax.faces.source": ctl,
                 f"{p}:javax.faces.partial.execute": ctl + (f" {F}" if advice else ""),
                 f"{p}:javax.faces.partial.render": f"{F}:modalDialog1" if advice else f"{F}:modalDialog",
                 f"{p}:javax.faces.partial.ajax": "true", f"{p}:javax.faces.behavior.event": "action"}
        if advice:
            extra.update(ServiceInvoiceNo=row["doc_no"], ServiceInvoiceDate=row["doc_date_dmy"], vendorCode=self.vendor)
        text = self._ajax(extra)
        m = [u for u in re.finditer(r'<update id="([^"]*)"><!\[CDATA\[(.*?)\]\]></update>', text, re.S)
             if "modalDialog" in u.group(1)]
        return m[0].group(2) if m else ""


def run(d1, d2, budget=None):
    """List every month, then fetch the notes not read yet. budget = seconds (website), None = no limit (PC)."""
    from . import status as st
    t0 = time.time()
    STATUS.update(running=True, log=[], started=datetime.now().isoformat(timespec="seconds"), finished="",
                  error="", result=None, more=False)
    listed = detailed = 0
    try:
        _log("Logging in to TAFE Channel - Account Info > Debit Credit Note / Intimation Details, View All")
        s = gh.login(config.read_env())
        for a, b in months(d1, d2):
            if budget and notes.listed_recently(a, b):
                continue                                  # done in an earlier call of this fetch
            pg = _Page(s, a, b)
            xls = pg.excel()
            n = notes.store_list(pg.rows, xls, a, b)
            listed += n
            todo = notes.pending(a, b)
            _log(f"{a:%d/%m/%Y} - {b:%d/%m/%Y}: {n} documents, {len(todo)} notes to read")
            for i, row in enumerate(todo, 1):
                if budget and time.time() - t0 > budget:
                    STATUS["more"] = True
                    break
                try:
                    notes.store_detail(row, pg.detail(row))
                    detailed += 1
                except gh.PortalError:
                    raise
                except Exception as e:  # noqa: BLE001
                    notes.store_detail(row, "", error=str(e))
                if i % 50 == 0:
                    _log(f"   read {i} of {len(todo)}")
            if STATUS["more"]:
                _log("Time is up for this call - continuing…")
                break
        left = notes.pending_count(d1, d2)
        STATUS["result"] = dict(documents=listed, read=detailed, left=left)
        STATUS["more"] = STATUS["more"] and left > 0
        _log(f"Done: {listed} documents, {detailed} notes read" + (f", {left} still to read" if left else ""))
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
    """Background run (PC / pc_jobs)."""
    with _lock:
        if STATUS["running"]:
            return False
        STATUS["running"] = True
    threading.Thread(target=run, args=(d1, d2), daemon=True).start()
    return True


def network_problem(msg):
    m = (msg or "").lower()
    return "did not answer" in m or "could not reach" in m or "timed out" in m


def default_dates():
    d2 = date.today()
    return d2.replace(day=1) - timedelta(days=31), d2
