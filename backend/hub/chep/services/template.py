"""CHEP portal Bulk Transfer template: read its Reference lists and fill it.

The file is filled by editing its XML directly instead of re-saving it with openpyxl,
so everything the portal put in it (hidden Reference sheet, sheet protection, drop-down
lists, the exact sheet name "BulkTransferTemplate.xlsx") stays exactly as it was.
openpyxl cannot even open the portal's file (it writes errorStyle="error", which is not
a valid Excel value) - that attribute is dropped, as Excel itself does when it saves.
"""
import io
import posixpath
import re
import zipfile
from datetime import date, timedelta
from xml.sax.saxutils import escape

COLUMNS = ["BP Code", "To Customer", "SKUs", "Quantity", "Doc Date",
           "Transporter Name", "Vehicle No", "LR No", "Invoice No", "Remarks"]
DATE_FMT = r"[$-F800]dddd\,\ mmmm\ dd\,\ yyyy"
COL_WIDTHS = [11, 13, 12.5, 9, 30, 17, 12, 8, 13, 50]


class TemplateError(Exception):
    pass


def _unescape(s):
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
            .replace("&apos;", "'").replace("&amp;", "&"))


def _sheet_paths(z):
    """[(sheet name, path inside zip)] in workbook order."""
    wb = z.read("xl/workbook.xml").decode("utf-8")
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    target = {}
    for m in re.finditer(r"<Relationship\b([^>]*)/?>", rels):
        a = m.group(1)
        rid = re.search(r'Id="([^"]+)"', a)
        tgt = re.search(r'Target="([^"]+)"', a)
        if rid and tgt:
            t = tgt.group(1)
            t = t.lstrip("/") if t.startswith("/") else posixpath.normpath(posixpath.join("xl", t))
            target[rid.group(1)] = t
    out = []
    for m in re.finditer(r"<sheet\b([^>]*)/>", wb):
        a = m.group(1)
        name = re.search(r'name="([^"]*)"', a).group(1)
        rid = re.search(r'r:id="([^"]+)"', a).group(1)
        out.append((_unescape(name), target[rid]))
    return out


def _shared_strings(z):
    try:
        x = z.read("xl/sharedStrings.xml").decode("utf-8")
    except KeyError:
        return []
    out = []
    for si in re.findall(r"<si>(.*?)</si>", x, re.S):
        out.append(_unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))))
    return out


def _cells(sheet_xml, sst):
    """{'A1': value} for every cell with a value."""
    out = {}
    for m in re.finditer(r'<c r="([A-Z]+\d+)"([^>]*?)(?:/>|>(.*?)</c>)', sheet_xml, re.S):
        ref, attrs, inner = m.group(1), m.group(2), m.group(3) or ""
        v = re.search(r"<v>(.*?)</v>", inner, re.S)
        t = re.search(r't="([^"]+)"', attrs)
        if t and t.group(1) == "s" and v:
            out[ref] = sst[int(v.group(1))]
        elif t and t.group(1) == "inlineStr":
            out[ref] = _unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", inner, re.S)))
        elif v:
            out[ref] = _unescape(v.group(1))
    return out


def _serial_to_date(v, up=False):
    try:
        f = float(v)
        n = int(f) + (1 if up and f > int(f) else 0)
        return (date(1899, 12, 30) + timedelta(days=n)).isoformat()
    except (TypeError, ValueError):
        return None


def template_info(data):
    """Reference lists and the Doc Date range the template allows."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        paths = _sheet_paths(z)
    except (zipfile.BadZipFile, KeyError, AttributeError) as e:
        raise TemplateError(f"Not a CHEP Bulk Transfer template ({e})")
    sst = _shared_strings(z)
    main_name, main_path = paths[0]
    main = z.read(main_path).decode("utf-8")
    header = _cells(main, sst)
    got = [header.get(f"{c}1", "") for c in "ABCDEFGHIJ"]
    if [g.strip().lower() for g in got[:5]] != [c.lower() for c in COLUMNS[:5]]:
        raise TemplateError("This is not the CHEP Bulk Transfer template - row 1 must be "
                            "BP Code, To Customer, SKUs, Quantity, Doc Date ...")
    ref = {"bp_codes": [], "customers": [], "skus": []}
    for name, path in paths[1:]:
        if name.lower() == "reference":
            cells = _cells(z.read(path).decode("utf-8"), sst)
            for col, key in (("A", "bp_codes"), ("B", "customers"), ("C", "skus")):
                rows = sorted((int(k[1:]), v) for k, v in cells.items() if re.fullmatch(col + r"\d+", k))
                ref[key] = [str(v).strip() for _, v in rows if str(v).strip()]
    rng = None
    m = re.search(r'<dataValidation[^>]*type="date"[^>]*>\s*<formula1>([\d.]+)</formula1>\s*<formula2>([\d.]+)</formula2>', main)
    if m:
        rng = dict(start=_serial_to_date(m.group(1), up=True), end=_serial_to_date(m.group(2)))
    return dict(sheet=main_name, columns=got, reference=ref, date_range=rng)


def has_rows(data):
    """True when the workbook is a FILLED template (a History / BulkTransfer file), not a blank one."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        paths = _sheet_paths(z)
        cells = _cells(z.read(paths[0][1]).decode("utf-8"), _shared_strings(z))
        return any(str(cells.get(f"{c}2", "")).strip() for c in "ABCD")
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- writing
def _col_letter(i):
    return "ABCDEFGHIJ"[i]


def _ensure_date_style(styles):
    """Returns (styles xml, index of a cellXfs entry with the long date format)."""
    fmt_id = None
    for m in re.finditer(r'<numFmt\b[^>]*numFmtId="(\d+)"[^>]*formatCode="([^"]*)"', styles):
        if _unescape(m.group(2)) == DATE_FMT:
            fmt_id = int(m.group(1))
    if fmt_id is None:
        ids = [int(x) for x in re.findall(r'<numFmt\b[^>]*numFmtId="(\d+)"', styles)]
        fmt_id = max(ids + [163]) + 1
        nf = f'<numFmt numFmtId="{fmt_id}" formatCode="{escape(DATE_FMT, {chr(34): "&quot;"})}"/>'
        if "<numFmts" in styles:
            styles = re.sub(r"(<numFmts[^>]*>)", lambda m: m.group(1) + nf, styles, count=1)
            styles = re.sub(r'<numFmts count="\d+"',
                            lambda m: f'<numFmts count="{len(re.findall("<numFmt ", styles))}"', styles, count=1)
        else:
            styles = re.sub(r"(<styleSheet\b[^>]*>)", lambda m: m.group(1) + f'<numFmts count="1">{nf}</numFmts>',
                            styles, count=1)
    xfs = re.search(r"<cellXfs[^>]*>(.*?)</cellXfs>", styles, re.S)
    items = re.findall(r"<xf\b[^>]*?(?:/>|>.*?</xf>)", xfs.group(1), re.S)
    for i, x in enumerate(items):
        if f'numFmtId="{fmt_id}"' in x:
            return styles, i
    new_xf = f'<xf numFmtId="{fmt_id}" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    body = xfs.group(1) + new_xf
    styles = styles[:xfs.start()] + re.sub(r'count="\d+"', f'count="{len(items) + 1}"',
                                           styles[xfs.start():xfs.start(1)], count=1) + body + "</cellXfs>" + styles[xfs.end():]
    return styles, len(items)


class _Strings:
    def __init__(self, xml):
        self.xml = xml or ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                           '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="0" uniqueCount="0"></sst>')
        self.items = re.findall(r"<si>.*?</si>", self.xml, re.S)
        self.index = {}
        for i, si in enumerate(self.items):
            m = re.fullmatch(r"<si><t(?: [^>]*)?>(.*?)</t></si>", si, re.S)
            if m:
                self.index.setdefault(_unescape(m.group(1)), i)
        self.new = []
        self.refs = 0

    def idx(self, s):
        self.refs += 1
        if s in self.index:
            return self.index[s]
        i = len(self.items) + len(self.new)
        sp = ' xml:space="preserve"' if s != s.strip() or "  " in s else ""
        self.new.append(f"<si><t{sp}>{escape(s)}</t></si>")
        self.index[s] = i
        return i

    def render(self):
        total = len(self.items) + len(self.new)
        x = self.xml.replace("</sst>", "".join(self.new) + "</sst>")
        m = re.search(r'<sst\b[^>]*?\scount="(\d+)"', self.xml)
        orig = int(m.group(1)) if m else len(self.items)
        x = re.sub(r'(<sst\b[^>]*?)\scount="\d+"', rf'\1 count="{orig + self.refs}"', x, count=1)
        x = re.sub(r'(<sst\b[^>]*?)\suniqueCount="\d+"', rf'\1 uniqueCount="{total}"', x, count=1)
        return x


def fill_template(data, rows):
    """rows: list of dicts with the 10 template columns. Returns the filled .xlsx bytes.

    Text columns are written as text (so 0019165124 keeps its zeros), Quantity as a
    number and Doc Date as a real Excel date shown as 'Monday, October 05, 2026'.
    """
    zin = zipfile.ZipFile(io.BytesIO(data))
    paths = _sheet_paths(zin)
    main_path = paths[0][1]
    sheet = zin.read(main_path).decode("utf-8")
    try:
        sst_xml = zin.read("xl/sharedStrings.xml").decode("utf-8")
    except KeyError:
        sst_xml = None
    strings = _Strings(sst_xml)
    styles, date_style = _ensure_date_style(zin.read("xl/styles.xml").decode("utf-8"))

    # keep row 1 (the header) exactly as the portal made it
    sd = re.search(r"<sheetData>(.*?)</sheetData>|<sheetData/>", sheet, re.S)
    head = re.search(r'<row r="1"[ >].*?</row>|<row r="1"[^>]*/>', sd.group(1) or "", re.S) if sd.group(1) else None
    out_rows = [head.group(0)] if head else []

    def cell(ref, v, style=None):
        s = f' s="{style}"' if style is not None else ""
        if v is None or v == "":
            return ""
        if isinstance(v, date):
            return f'<c r="{ref}"{s}><v>{(v - date(1899, 12, 30)).days}</v></c>'
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            n = int(v) if float(v).is_integer() else v
            return f'<c r="{ref}"{s}><v>{n}</v></c>'
        return f'<c r="{ref}"{s} t="s"><v>{strings.idx(str(v))}</v></c>'

    keys = ["bp_code", "customer", "sku", "qty", "doc_date", "transporter", "vehicle", "lr", "invoice", "remarks"]
    for n, r in enumerate(rows, start=2):
        cells = "".join(cell(f"{_col_letter(i)}{n}", r.get(k), date_style if k == "doc_date" else None)
                        for i, k in enumerate(keys))
        out_rows.append(f'<row r="{n}" spans="1:10">{cells}</row>')
    last = len(rows) + 1
    new_sd = "<sheetData>" + "".join(out_rows) + "</sheetData>"
    sheet = sheet[:sd.start()] + new_sd + sheet[sd.end():]
    sheet = re.sub(r'<dimension ref="[^"]*"/>', f'<dimension ref="A1:J{max(last, 1)}"/>', sheet, count=1)
    sheet = sheet.replace(' errorStyle="error"', "")
    if "<cols>" not in sheet:
        cols = "<cols>" + "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
                                  for i, w in enumerate(COL_WIDTHS, start=1)) + "</cols>"
        sheet = sheet.replace("<sheetData>", cols + "<sheetData>", 1)

    # drop-down / date checks must reach the last row
    def widen(m):
        return re.sub(r"([A-J])(\d+):([A-J])(\d+)",
                      lambda r: f"{r.group(1)}{r.group(2)}:{r.group(3)}{max(int(r.group(4)), last)}", m.group(0))
    sheet = re.sub(r'sqref="[^"]*"', widen, sheet)
    sheet = re.sub(r"<xm:sqref>[^<]*</xm:sqref>", widen, sheet)

    replaced = {main_path: sheet, "xl/styles.xml": styles, "xl/sharedStrings.xml": strings.render()}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            body = replaced.pop(item.filename, None)
            zout.writestr(item, body.encode("utf-8") if body is not None else zin.read(item.filename))
        if "xl/sharedStrings.xml" in replaced:  # template had no shared strings part
            raise TemplateError("Template has no shared strings part - upload the template from the CHEP portal.")
    return buf.getvalue()
