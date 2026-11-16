"""
TAFE Channel "PO Details", read without a browser (taken from Ore: sdew-erp services/core/app/modules/tafe/portal.py).
Logs in with the hub's TAFE Channel login (supp/services/grin_http.py, TAFE_USER / TAFE_PASS) and sends the form
the page itself sends. Checked by hand on 12 Nov 2026 in the portal:

* the form has Period or PO Number; From and To date (dd/mm/yyyy, at most one year apart: "To date should
  not be more than a year"); Company (TAFE); Plant (one plant at a time); PO Type (Regular, Development,
  Spares, ALL); and the Fetch button (<form>:button);
* the answer is a table <form>:asyncTable1, 25 rows a page; <form>:asyncTable1__rows=5000 returns every row;
* columns: Plant, PO Number, PO Date, Valid Till Date, CT-2 Value, Docket No., CT-2 Confirmed Date,
  PO Line No., Part Details ("part - description"), Issue No., Currency, Rate(Rs), Per UOM, Total Qty,
  Value(Rs), Delivered Qty, Taxes, Excise Duty, Basic Price, Freight Amt, Packing Amt, Price Effect From,
  Price Confirm Date. "30/11/0002" means no date.

Only reads. Never sends anything to TAFE but the search form.
"""
import html
import re
import urllib.parse
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

PAGE = "/PODetails"
COLUMNS = {
    "Plant": "plant", "PO Number": "po_no", "PO Date": "po_date", "Valid Till Date": "valid_till",
    "PO Line No.": "line_no", "Part Details": "part_details", "Issue No.": "issue_no", "Currency": "currency",
    "Rate(Rs)": "rate", "Per UOM": "uom", "Total Qty": "total_qty", "Value(Rs)": "value",
    "Delivered Qty": "delivered_qty", "Price Effect From": "price_from", "Price Confirm Date": "price_confirmed",
    "Basic Price": "basic", "Freight Amt": "freight", "Packing Amt": "packing",
}


class TafePortalError(Exception):
    """TAFE Channel could not be read; the message says why in plain words."""


# ---------------------------------------------------------------------------
# Reading the page
# ---------------------------------------------------------------------------

class _Page(HTMLParser):
    """The PO form (its fields and the plant list with names) and the results table, if any."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms: List[dict] = []
        self.form: Optional[dict] = None
        self.select: Optional[str] = None
        self.option: Optional[str] = None
        self.table_depth = 0          # inside the results table (counts nested tables)
        self.row: Optional[List[str]] = None
        self.row_kind = ""
        self.cell: Optional[List[str]] = None
        self.skip = 0                 # inside <script>/<style>
        self.header: List[str] = []
        self.rows: List[List[str]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "form":
            self.form = dict(id=a.get("id", ""), action=a.get("action", ""), inputs=[], selects={})
            self.forms.append(self.form)
        elif tag == "input" and self.form is not None and a.get("name"):
            self.form["inputs"].append((a["name"], (a.get("type") or "text").lower(), a.get("value") or "",
                                        "checked" in a))
        elif tag == "select" and self.form is not None and a.get("name"):
            self.select = a["name"]
            self.form["selects"][self.select] = []
        elif tag == "option" and self.select:
            self.option = a.get("value") or ""
            self.form["selects"][self.select].append([self.option, ""])
        elif tag == "table":
            if self.table_depth or (a.get("id") or "").endswith(":asyncTable1"):
                self.table_depth += 1
        elif self.table_depth and tag == "tr":
            cls = a.get("class") or ""
            # data rows alternate between portlet-section-body and portlet-section-alternate
            self.row_kind = ("head" if "section-header" in cls else
                             "body" if ("section-body" in cls or "section-alternate" in cls) else "")
            self.row = [] if self.row_kind else None
        elif self.row is not None and tag in ("td", "th"):
            self.cell = []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag == "form":
            self.form = None
        elif tag == "select":
            self.select = None
        elif tag == "option":
            self.option = None
        elif tag == "table" and self.table_depth:
            self.table_depth -= 1
        elif self.row is not None and tag in ("td", "th") and self.cell is not None:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row_kind == "head" and not self.header:
                self.header = self.row
            elif self.row_kind == "body" and self.row:
                self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.skip:
            return
        if self.option is not None and self.select:
            self.form["selects"][self.select][-1][1] += data
        if self.cell is not None:
            self.cell.append(data)


def read_page(text: str) -> _Page:
    p = _Page()
    p.feed(text)
    return p


def po_form(page: _Page) -> Optional[dict]:
    return next((f for f in page.forms if any(n.endswith(":Plant1") for n in f["selects"])), None)


def plants(page: _Page) -> List[Tuple[str, str]]:
    """(code, name) of every TAFE plant in the Plant list: "Doddaballapur Plant - 1030" -> ("1030", "Doddaballapur Plant")."""
    form = po_form(page)
    if not form:
        return []
    opts = next(v for k, v in form["selects"].items() if k.endswith(":Plant1"))
    out = []
    for value, label in opts:
        label = re.sub(r"\s+", " ", label).strip()
        if not re.fullmatch(r"\d{3,6}", value or ""):
            continue
        name = re.sub(rf"\s*-\s*{re.escape(value)}\s*$", "", label).strip() or label
        out.append((value, name))
    return out


def _day(text: str) -> Optional[date]:
    try:
        d = datetime.strptime((text or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None
    return d if d.year >= 1990 else None   # TAFE shows 30/11/0002 when there is no date


def _num(text: str) -> Decimal:
    t = (text or "").replace(",", "").strip()
    try:
        return Decimal(t) if t else Decimal("0")
    except InvalidOperation:
        raise TafePortalError(f"TAFE Channel shows a number the hub cannot read: {text!r}") from None


def po_rows(page: _Page) -> List[dict]:
    """The PO lines in the results table, by column name. Rows without a plant code are left out."""
    if not page.header:
        return []
    idx = {COLUMNS[h]: i for i, h in enumerate(page.header) if h in COLUMNS}
    missing = [c for c in ("plant", "po_no", "po_date", "line_no", "part_details", "rate") if c not in idx]
    if missing:
        raise TafePortalError("TAFE Channel's PO Details table has changed: no column " + ", ".join(missing))
    out = []
    for r in page.rows:
        def g(k, r=r):
            return r[idx[k]] if k in idx and idx[k] < len(r) else ""
        if not re.fullmatch(r"\d{3,6}", g("plant")) or not g("po_no"):
            continue
        detail = g("part_details")
        part, _, desc = detail.partition(" - ")
        out.append(dict(
            plant=g("plant"), po_no=g("po_no"), po_date=_day(g("po_date")), valid_till=_day(g("valid_till")),
            line_no=int(_num(g("line_no")) or 0), part_no=part.strip().upper(), description=(desc or detail).strip()[:255],
            issue_no=g("issue_no") or None, currency=g("currency") or "INR", rate=_num(g("rate")), uom=g("uom") or None,
            total_qty=_num(g("total_qty")), value=_num(g("value")), delivered_qty=_num(g("delivered_qty")),
            price_from=_day(g("price_from")), price_confirmed=_day(g("price_confirmed")),
            basic=_num(g("basic")) if "basic" in idx else None, freight=_num(g("freight")) if "freight" in idx else None,
            packing=_num(g("packing")) if "packing" in idx else None))
    return out


# ---------------------------------------------------------------------------
# Talking to TAFE Channel
# ---------------------------------------------------------------------------

def year_back(d: date, years: int = 1) -> date:
    """The day after the same date `years` years earlier: 12/11/2026 -> 13/11/2025 (one TAFE "year")."""
    try:
        back = d.replace(year=d.year - years)
    except ValueError:            # 29 February
        back = d.replace(year=d.year - years, day=28)
    return back + timedelta(days=1)


def windows(start: date, end: date) -> List[Tuple[date, date]]:
    """end back to start in pieces of at most one year (TAFE refuses longer periods), newest first."""
    out, b = [], end
    while b >= start:
        a = max(start, year_back(b))
        out.append((a, b))
        b = a - timedelta(days=1)
    return out


def _fields(form: dict, plant: str, d1: Optional[date], d2: Optional[date], button: str = "button",
            po_no: str = "") -> List[Tuple[str, str]]:
    out = []
    for name, typ, value, checked in form["inputs"]:
        if typ in ("submit", "button", "image", "reset", "file") or name == "__fc":
            continue
        if typ == "radio":
            if name.endswith(":htmlSelectOneRadio"):
                if (value == "Period") != bool(po_no):          # Period, or the other choice (PO Number)
                    out.append((name, value))
            elif checked:
                out.append((name, value))
            continue
        if typ == "checkbox" and not checked:
            continue
        if name.endswith(":fromdt__date"):
            value = d1.strftime("%d/%m/%Y") if d1 else ""
        elif name.endswith(":todt__date"):
            value = d2.strftime("%d/%m/%Y") if d2 else ""
        elif name.endswith(":asyncTable1__rows"):
            value = "5000"
        elif name.endswith(":asyncTable1__first"):
            value = "0"
        elif name.endswith(":ponumber"):
            value = po_no or ""
        elif name.endswith(":partnumber"):
            value = ""
        out.append((name, value))
    for name, opts in form["selects"].items():
        values = [v for v, _ in opts]
        if name.endswith(":Plant1"):
            out.append((name, plant))
        elif name.endswith(":potype"):
            out.append((name, "ALL"))
        elif "TAFE" in values:
            out.append((name, "TAFE"))
        else:
            out.append((name, values[0] if values else ""))
    # The page's script adds the table's paging fields only in a browser; without them TAFE answers 25 rows.
    names = {n for n, _ in out}
    for suffix, value in ((":asyncTable1__rows", "5000"), (":asyncTable1__first", "0")):
        if not any(n.endswith(suffix) for n in names):
            out.append((f"{form['id']}{suffix}", value))
    out.append(("__fc", f"{form['id']}:{button}"))
    return out


class Channel:
    """A logged in TAFE Channel session (the hub's login: TAFE_USER and TAFE_PASS from .env / Vercel)."""

    def __init__(self):
        from .. import config
        from ..supp.services import grin_http

        self._gh = grin_http
        try:
            self.session = grin_http.login(config.read_env())
        except grin_http.PortalError as exc:
            raise TafePortalError(str(exc)) from None

    def _post(self, url: str, page: "_Page", fields) -> Tuple[str, bytes]:
        form = po_form(page)
        action = urllib.parse.urljoin(url, html.unescape(form["action"]) or url)
        try:
            url2, _, body = self.session.post(action, fields, referer=url)
        except Exception as exc:  # noqa: BLE001
            raise TafePortalError(self._gh._net_msg(exc)) from None
        self._last = body
        return url2, body

    def _get(self) -> Tuple[str, _Page]:
        """The PO Details page with the plant list filled in. A fresh page lists the plants only after the
        company is chosen: the page then runs its hidden command <form>:hidden, which is what we send."""
        if getattr(self, "_ready", None):
            return self._ready
        try:
            url, _, body = self.session.get(PAGE)
        except Exception as exc:  # noqa: BLE001
            raise TafePortalError(self._gh._net_msg(exc)) from None
        self._last = body
        page = read_page(body.decode("utf-8", errors="replace"))
        if not po_form(page):
            raise TafePortalError("TAFE Channel did not show the PO Details page (is the login still allowed there?)")
        if not plants(page):
            url, body = self._post(url, page, _fields(po_form(page), "null", None, None, "hidden"))
            page = read_page(body.decode("utf-8", errors="replace"))
            if not po_form(page):
                raise TafePortalError(f"TAFE Channel did not list the plants - saved as {self._debug('po_company', body)}")
        self._ready = (url, page)
        return url, page

    def _debug(self, name: str, body: bytes) -> str:
        """Keep a page TAFE Channel answered unexpectedly, to check by hand (data/tafe_debug)."""
        import os

        from .. import config

        folder = os.path.join(config.DATA_DIR, "tafe_debug")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{datetime.now():%Y%m%d_%H%M%S}_{name}.html")
        with open(path, "wb") as fh:
            fh.write(body)
        return path

    def plants(self) -> List[Tuple[str, str]]:
        url, page = self._get()
        found = plants(page)
        if not found:
            self._debug("po_page_no_plants", self._last)
        return found

    def po_lines(self, plant: str, d1: date, d2: date) -> List[dict]:
        url, page = self._get()
        url2, body = self._post(url, page, _fields(po_form(page), plant, d1, d2))
        answer = read_page(body.decode("utf-8", errors="replace"))
        rows = po_rows(answer)
        total = shown_total(body.decode("utf-8", errors="replace"))
        if total and len(rows) < total and po_form(answer):
            # A page without results has no rows-per-page field, so the first answer holds 25 rows. The
            # answer's form has it: ask again with every row.
            url2, body = self._post(url2, answer, _fields(po_form(answer), plant, d1, d2))
            answer = read_page(body.decode("utf-8", errors="replace"))
            rows = po_rows(answer)
            if len(rows) < total:
                raise TafePortalError(f"TAFE Channel gave {len(rows)} of {total} PO lines for plant {plant}; "
                                      f"saved as {self._debug(f'po_{plant}_short', body)}")
        # the answer is the same page with the results: its form (fresh view state) serves the next search
        self._ready = (url2, answer) if po_form(answer) and plants(answer) else None
        if not answer.header and "asyncTable1" in body.decode("utf-8", errors="replace"):
            self._debug(f"po_{plant}_unread", body)
        return [r for r in rows if r["plant"] == plant]


def _po_lines_by_number(self, plant: str, po_no: str) -> List[dict]:
    """One PO by its number (POs older than the date window, e.g. the 2017 schedule POs valid till 2030)."""
    url, page = self._get()
    url2, body = self._post(url, page, _fields(po_form(page), plant, None, None, po_no=po_no))
    answer = read_page(body.decode("utf-8", errors="replace"))
    rows = po_rows(answer)
    total = shown_total(body.decode("utf-8", errors="replace"))
    if total and len(rows) < total and po_form(answer):
        url2, body = self._post(url2, answer, _fields(po_form(answer), plant, None, None, po_no=po_no))
        answer = read_page(body.decode("utf-8", errors="replace"))
        rows = po_rows(answer)
    self._ready = (url2, answer) if po_form(answer) and plants(answer) else None
    if not rows:
        self._debug(f"po_{po_no}_none", body)
    return [r for r in rows if r["po_no"] == po_no]


Channel.po_by_number = _po_lines_by_number


def shown_total(text: str) -> Optional[int]:
    """The "1 - 25 of 64" under the results table: 64."""
    m = re.search(r"\b\d+\s*-\s*\d+\s+of\s+(\d+)\b", re.sub(r"<[^>]+>", " ", text))
    return int(m.group(1)) if m else None


def group_by_po(rows: List[dict]) -> Dict[str, dict]:
    pos: Dict[str, dict] = {}
    for r in rows:
        po = pos.setdefault(r["po_no"], dict(po_no=r["po_no"], plant=r["plant"], po_date=r["po_date"],
                                             valid_till=r["valid_till"], lines={}))
        po["lines"][r["line_no"]] = r
    return pos
