"""TAFE's own books: Account Info > Account Balance-Outstanding on TAFE Channel, fetched every day.

What a person does (screenshot 07-Nov-2026): Company = TAFE -> Fetch -> 10 balances (advances, 'General Acct. Bal.')
-> pick 'General Acct. Bal.' -> 'Outstanding Details': every document TAFE has booked and not paid yet
(Doc No, Line, Document Date, Doc Type RF/RG = our invoice booked, ZK = their debit note, GRIN Date,
Invoice / Reference No, Debit, Credit, Narration). Checked live: 220 lines, credit 20,91,021.68 - debit 2,700.21
= 20,88,321.47 = the General Acct. Bal. (shown negative: TAFE owes us).
We send the same two full-page posts the page sends (Fetch, then the row pick with the table size raised).
Runs once a day by itself (PC: after BALANCE_HOUR, default 9; website: Vercel cron) and with the Fetch button.
"""
import html
import re
import threading
import time
import traceback
import urllib.parse
from datetime import datetime
from html.parser import HTMLParser

from ... import config
from ...supp.services import grin_http as gh

PAGE = "/meta/default/wm_xt_fabricfolder/0000012123"
STATUS = dict(running=False, log=[], started="", finished="", error="", result=None)
_lock = threading.Lock()
_daily_on = False


def _log(msg):
    STATUS["log"].append(f"{datetime.now():%H:%M:%S}  {msg}")
    STATUS["log"] = STATUS["log"][-40:]
    print("[TAFE balance]", msg)


class _Rows(HTMLParser):
    """Rows of the two tables: id '...:BalanceResults:__row<n>' / '...:OSResults:__row<n>' -> cell texts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.cur, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            m = re.search(r":(BalanceResults|OSResults):__row(\w+)$", a.get("id") or "")
            if m and not m.group(2).startswith("_"):
                self.cur = dict(table=m.group(1), rid=m.group(2), cells=[])
                self.rows.append(self.cur)
        elif tag == "td" and self.cur is not None:
            self.cell = []
            self.cur["cells"].append(self.cell)

    def handle_endtag(self, tag):
        if tag == "tr":
            self.cur, self.cell = None, None

    def handle_data(self, d):
        if self.cell is not None and d.strip():
            self.cell.append(d.strip())


def _num(s):
    try:
        return float(str(s).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def parse(page):
    """-> (balances [{sno, rid, name, amount}], lines [{doc_no, line, doc_date, doc_type, grin_date, ref, debit, credit, narration}])"""
    from .norm import iso
    p = _Rows()
    p.feed(page)
    bal, lines, seen = [], [], set()
    for r in p.rows:
        c = [" ".join(x).strip() for x in r["cells"]]
        if (r["table"], r["rid"]) in seen:
            continue
        seen.add((r["table"], r["rid"]))
        if r["table"] == "BalanceResults":
            nums = [x for x in c if re.fullmatch(r"-?[\d,]+\.\d+", x)]
            name = next((x for x in c if re.search(r"[A-Za-z]", x)), "")
            if name:
                bal.append(dict(rid=r["rid"], name=name, amount=_num(nums[-1]) if nums else 0.0))
        else:
            # S.No | Doc No | Line | Document Date | Doc Type | GRIN Date | Invoice/Ref | Debit | Credit | (blank) | Narration
            i = next((k for k in range(len(c) - 2) if re.fullmatch(r"\d{6,}", c[k])
                      and re.fullmatch(r"\d{2}/\d{2}/\d{4}", c[k + 2] or "")), None)
            if i is None:
                continue
            rest = c[i:] + [""] * 10
            lines.append(dict(doc_no=rest[0], line=rest[1], doc_date=iso(rest[2]), doc_type=rest[3].upper(),
                              grin_date=iso(rest[4]) if re.match(r"\d", rest[4]) else "", ref=rest[5],
                              debit=round(_num(rest[6]), 2), credit=round(_num(rest[7]), 2),
                              narration=rest[9] or rest[8]))
    return bal, lines


def _form(page):
    """The page's form: the one with the Company list (TAFE). Fetch / fetchOS are <button>s, not inputs."""
    for f in gh._forms(page):
        if any("TAFE" in opts for opts in f["selects"].values()) or \
                any("BalanceResults" in n for n, *_ in f["inputs"]):
            return f
    return None


def _fields(form, extra):
    out, names = [], set()
    for name, typ, value, checked in form["inputs"]:
        if typ in ("submit", "button", "image", "reset", "file") or not name or name in extra:
            continue
        if typ in ("checkbox", "radio") and not checked:
            continue
        out.append((name, value))
        names.add(name)
    for name, opts in form["selects"].items():
        if name not in extra:
            out.append((name, "TAFE" if "TAFE" in opts else form["selected"].get(name, opts[0] if opts else "")))
    out += list(extra.items())
    return out


def fetch(s):
    """One logged-in session -> dict(balances, lines). Raises gh.PortalError."""
    try:
        url, _, body = s.get(PAGE)
        page = gh._text(body)
        form = _form(page)
        if not form:
            raise gh.PortalError(f"Account Balance page not found - saved as {gh._debug('bal_page', body)}")
        F = form["id"]
        act = urllib.parse.urljoin(url, html.unescape(form["action"]) or url)
        url2, _, body2 = s.post(act, _fields(form, {"__fc": f"{F}:fetchButton1"}), referer=url)      # Fetch
        page2 = gh._text(body2)
        bal, _ = parse(page2)
        form2 = _form(page2)
        if not bal or not form2:
            raise gh.PortalError(f"Fetch did not return the balances - saved as {gh._debug('bal_after_fetch', body2)}")
        gen = next((b for b in bal if "general" in b["name"].lower()), bal[-1])
        act2 = urllib.parse.urljoin(url2, html.unescape(form2["action"]) or url2)
        # the tables' pager / selection fields are written by the page's JavaScript - without them TAFE answers
        # "Index 0 out of bounds for length 0" (checked 07-Nov-2026), so send them like the browser does
        extra = {"__fc": f"{F}:fetchOS",
                 f"{F}:BalanceResults__update": ",".join(f"__row{b['rid']}" for b in bal),
                 f"{F}:BalanceResults__selection": f"selected:{gen['rid']}",
                 f"{F}:BalanceResults__firstByID": "", f"{F}:BalanceResults__first": "0",
                 f"{F}:BalanceResults__rows": str(max(10, len(bal))),
                 f"{F}:OSResults__update": "", f"{F}:OSResults__firstByID": "", f"{F}:OSResults__first": "0",
                 f"{F}:OSResults__rows": "5000"}
        url3, _, body3 = s.post(act2, _fields(form2, extra), referer=url2)                        # pick the row
        page3 = gh._text(body3)
        bal3, lines = parse(page3)
        total = _pager_total(page3)
        if total and len(lines) < total:
            # a fresh login shows only the first 30 lines: ask again now that the row is picked (TAFE keeps the
            # pick), then fall back to Export as Excel, which has every line
            form3 = _form(page3)
            if form3:
                act3 = urllib.parse.urljoin(url3, html.unescape(form3["action"]) or url3)
                _, _, body4 = s.post(act3, _fields(form3, extra), referer=url3)
                b4, l4 = parse(gh._text(body4))
                if len(l4) > len(lines):
                    lines, bal3 = l4, b4 or bal3
                if len(lines) < total:
                    xl = _excel(s, act3, form3, F, url3, extra)
                    if len(xl) > len(lines):
                        lines = xl
            if len(lines) < total:
                raise gh.PortalError(f"TAFE gave {len(lines)} of {total} outstanding lines - saved as "
                                     f"{gh._debug('bal_partial', body3)}")
    except gh.PortalError:
        raise
    except Exception as e:  # noqa: BLE001
        raise gh.PortalError(gh._net_msg(e))
    owed = round(sum(x["credit"] for x in lines) - sum(x["debit"] for x in lines), 2)
    if lines and abs(owed + gen["amount"]) > 1:
        _log(f"Note: lines add up to {owed:,.2f}, TAFE's balance is {-gen['amount']:,.2f}")
    if not lines and abs(gen["amount"]) > 1:
        raise gh.PortalError(f"Outstanding details did not come - saved as {gh._debug('bal_after_pick', body3)}")
    return dict(balances=bal3 or bal, lines=lines, general=gen["name"])


def _pager_total(page):
    m = re.findall(r"\d+\s*-\s*\d+\s+of\s+(\d+)", page)
    return int(m[-1]) if m else 0


def _excel(s, act, form, F, ref, extra):
    """Export as Excel of the outstanding details -> lines (same dicts as parse())."""
    import os
    import tempfile
    from .norm import iso
    from ...supp.services.readers import sheets
    ex = dict(extra)
    ex["__fc"] = f"{F}:excelCommandButton"
    try:
        _, _, data = s.post(act, _fields(form, ex), referer=ref)
    except Exception:  # noqa: BLE001
        return []
    if data[:4] != b"\xd0\xcf\x11\xe0" and data[:2] != b"PK":
        return []
    fd, path = tempfile.mkstemp(suffix=".xls")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    out = []
    try:
        for _, it in sheets(path):
            head = None
            for row in it:
                c = ["" if v is None else str(v).strip() for v in row]
                low = [x.lower() for x in c]
                if head is None:
                    if any(x.startswith("doc no") for x in low) and any("credit" in x for x in low):
                        head = {k: next((i for i, x in enumerate(low) if x.startswith(w)), None) for k, w in (
                            ("doc", "doc no"), ("line", "doc line"), ("date", "document date"), ("type", "doc type"),
                            ("grin", "grin date"), ("ref", "invoice"), ("debit", "debit"), ("credit", "credit"),
                            ("nar", "narration"))}
                    continue
                g = lambda k: c[head[k]] if head.get(k) is not None and head[k] < len(c) else ""  # noqa: E731
                doc = g("doc")[:-2] if g("doc").endswith(".0") else g("doc")
                if not re.fullmatch(r"\d{6,}", doc or ""):
                    continue
                out.append(dict(doc_no=doc, line=g("line").replace(".0", ""), doc_date=iso(g("date")),
                                doc_type=g("type").upper(), grin_date=iso(g("grin")), ref=g("ref"),
                                debit=round(_num(g("debit")), 2), credit=round(_num(g("credit")), 2), narration=g("nar")))
            break
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return out


def run(source="manual"):
    from . import balance
    STATUS.update(running=True, log=[], started=datetime.now().isoformat(timespec="seconds"), finished="",
                  error="", result=None)
    try:
        _log("Logging in to TAFE Channel - Account Info > Account Balance-Outstanding, Company TAFE")
        s = gh.login(config.read_env())
        got = fetch(s)
        res = balance.store(got, source)
        STATUS["result"] = res
        _log(f"Done: TAFE owes Rs {res['owed']:,.2f} on {res['lines']} documents "
             f"(credit {res['credit']:,.2f} - debit {res['debit']:,.2f})")
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
    return STATUS


def start(*_a, **_k):
    with _lock:
        if STATUS["running"]:
            return False
        STATUS["running"] = True
    threading.Thread(target=run, daemon=True).start()
    return True


def network_problem(msg):
    m = (msg or "").lower()
    return "did not answer" in m or "could not reach" in m or "timed out" in m


def daily_hour():
    try:
        return min(23, max(0, int(config.read_env().get("BALANCE_HOUR") or 9)))
    except ValueError:
        return 9


def start_daily():
    """PC only: once a day after BALANCE_HOUR (or at start if today's is missing), like the nightly backup."""
    global _daily_on
    if _daily_on or config.ON_VERCEL or str(config.read_env().get("BALANCE_DAILY", "1")).strip() in ("0", "no", "off"):
        return
    _daily_on = True

    def loop():
        from . import balance
        time.sleep(90)
        while True:
            try:
                now = datetime.now()
                last = balance.last_fetch_date()
                if now.hour >= daily_hour() and last < now.date().isoformat() and not STATUS["running"]:
                    run("daily (PC)")
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            time.sleep(1800)

    threading.Thread(target=loop, daemon=True, name="tafe-balance").start()
    print(f"[TAFE balance] daily fetch on (after {daily_hour()}:00)")
