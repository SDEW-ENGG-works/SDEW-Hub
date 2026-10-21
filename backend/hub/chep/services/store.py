"""Uploading packing lists, the active template, and making the CHEP file."""
import json
import os
import re
from datetime import date, datetime

from .. import config
from ..db import get_db, one
from ..http import ApiError
from .builder import build_rows, checks, learn, remember_choices, resolve
from .defaults import load_settings
from .packing import parse_packing_list
from .template import TemplateError, fill_template, template_info


def _safe(name):
    return re.sub(r"[^\w.\- ()]+", "_", os.path.basename(name))[:120] or "upload"


# ---------------------------------------------------------------- template
def active_template():
    """(name, bytes, uploaded_at) of the template in use."""
    r = one("SELECT name, data, uploaded_at FROM templates ORDER BY id DESC LIMIT 1")
    if r:
        return r["name"], r["data"], r["uploaded_at"]
    with open(config.DEFAULT_TEMPLATE, "rb") as fh:
        return "BulkTransfer Template.xlsx (came with the app)", fh.read(), None


def template_summary():
    name, data, at = active_template()
    try:
        info = template_info(data)
    except TemplateError as e:
        info = {"error": str(e)}
    return dict(name=name, uploaded_at=at, **info)


def save_template(name, data):
    try:
        info = template_info(data)
    except TemplateError as e:
        raise ApiError(str(e))
    con = get_db()
    con.execute("INSERT INTO templates(name, uploaded_at, data) VALUES(?,?,?)",
                (name, datetime.now().isoformat(timespec="seconds"), data))
    con.commit()
    return info


# ---------------------------------------------------------------- packing list
def is_template(data):
    try:
        template_info(data)
        return True
    except Exception:
        return False


def ingest(name, data):
    """A packing list -> new batch. A blank CHEP template dropped here replaces the template."""
    if data[:2] == b"PK" and is_template(data):
        from .template import has_rows
        if has_rows(data):
            raise ApiError(f"{name} is a filled CHEP file (it already has rows), not the blank template - "
                           "it was not saved. Made files are in History.")
        info = save_template(name, data)
        return dict(kind="template", message="New CHEP template saved", template=info)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stored = os.path.join(config.UPLOAD_DIR, f"{stamp}_{_safe(name)}")
    with open(stored, "wb") as fh:
        fh.write(data)
    settings = load_settings()
    try:
        parsed = parse_packing_list(stored, settings)
    except Exception as e:  # noqa: BLE001 - tell the user what went wrong
        raise ApiError(f"Could not read {name}: {e}")
    if not parsed["sheets"]:
        raise ApiError("No packing list found in this file (looked for a header row with "
                       "'Invoice No' and 'CHEP' columns).")
    learned = learn(parsed, name)
    con = get_db()
    cur = con.execute("INSERT INTO batches(name, stored, uploaded_at, parsed, data) VALUES(?,?,?,?,?)",
                      (name, stored, datetime.now().isoformat(timespec="seconds"), json.dumps(parsed), data))
    con.commit()
    return dict(kind="packing", batch_id=cur.lastrowid, learned=learned)


def get_batch(bid):
    b = one("SELECT id, name, uploaded_at, parsed FROM batches WHERE id=?", (bid,))
    if not b:
        raise ApiError("Packing list not found", 404)
    b["parsed"] = json.loads(b["parsed"])
    return b


def reparse(bid):
    """Read the stored packing list again (after Settings changed)."""
    b = one("SELECT stored, name, data FROM batches WHERE id=?", (bid,))
    if not b:
        raise ApiError("Packing list not found", 404)
    path = b["stored"]
    if b["data"]:  # the file itself is kept in the database (needed on Vercel)
        path = os.path.join(config.UPLOAD_DIR, f"batch{bid}_{_safe(b['name'])}")
        with open(path, "wb") as fh:
            fh.write(bytes(b["data"]))
    elif not path or not os.path.exists(path):
        raise ApiError("The uploaded file is no longer in the data folder - upload it again.")
    parsed = parse_packing_list(path, load_settings())
    learn(parsed, b["name"])
    con = get_db()
    con.execute("UPDATE batches SET parsed=? WHERE id=?", (json.dumps(parsed), bid))
    con.commit()


# ---------------------------------------------------------------- build
def _doc_date(v):
    if not v:
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise ApiError("Doc Date is not a date")


def sent_invoices(bid):
    """{invoice no: (file name, made on dd-mm-yyyy)} from every History file NOT made from this
    same upload (making the same upload's file again must not hide its own invoices)."""
    out = {}
    con = get_db()
    for r in con.execute("SELECT file_name, created_at, rows FROM chep_runs WHERE batch_id IS NOT ? ORDER BY id",
                         (bid,)).fetchall():
        made = (r["created_at"] or "")[:10]
        made = f"{made[8:10]}-{made[5:7]}-{made[:4]}" if len(made) == 10 else made
        for row in json.loads(r["rows"] or "[]"):
            inv = str(row.get("invoice") or "").strip()
            if inv and inv not in out:
                out[inv] = (r["file_name"], made)
    return out


def prepare(bid, body):
    b = get_batch(bid)
    settings = load_settings()
    parsed = b["parsed"]
    selected = set(body.get("sheets") or [s["name"] for s in parsed["sheets"] if s["selected"]])
    choices = {k: str(v) for k, v in (body.get("choices") or {}).items() if v}
    resend = set(body.get("resend") or [])
    lines = resolve(parsed, selected, choices, settings, sent_invoices(bid), resend)
    d = _doc_date(body.get("doc_date"))
    extra = {k: str(body.get(k) or "").strip() for k in ("transporter", "vehicle", "lr")}
    rows = build_rows(lines, settings, d, extra)
    _, tdata, _ = active_template()
    try:
        tinfo = template_info(tdata)
    except TemplateError:
        tinfo = None
    warn = checks(lines, rows, settings, tinfo, d)
    summary = dict(
        sheets=sorted(selected), rows=len(rows),
        invoices=len({ln["invoice"] for ln in lines if ln["how"] not in ("carton", "missing", "already")}),
        cheps=sum(sum(ln["types"].values()) for ln in lines if ln["how"] not in ("carton", "missing", "already")),
        carton_only=sum(1 for ln in lines if ln["how"] == "carton"),
        already=sum(1 for ln in lines if ln["how"] == "already"),
        resent=sum(1 for ln in lines if ln.get("resent")),
        missing=sum(1 for ln in lines if ln["how"] == "missing"),
        from_history=sum(1 for ln in lines if ln["how"] == "part history"),
        by_plant={})
    for r in rows:
        if r["sku"] == settings_type_pallet(settings, r["type"]):
            summary["by_plant"][r["plant"]] = summary["by_plant"].get(r["plant"], 0) + r["qty"]
    return b, settings, lines, rows, warn, summary, tdata


def settings_type_pallet(settings, code):
    for t in settings["types"]:
        if str(t["code"]) == str(code):
            return t["pallet"]
    return None


def _rows_json(rows):
    return [dict(r, doc_date=r["doc_date"].isoformat() if r["doc_date"] else None) for r in rows]


def preview(bid, body):
    b, settings, lines, rows, warn, summary, _ = prepare(bid, body)
    return dict(lines=lines, rows=_rows_json(rows), warnings=warn, summary=summary)


# The CHEP portal reads only rows 2-201 of the template (200 rows) - rows below are silently
# dropped although it reports success (found 13-Oct-2026: rows 202+ of a 268-row file were lost).
MAX_ROWS = 200


def package(tdata, rows, fname):
    """(file name, bytes) - one .xlsx, or a .zip of 'part 1 of N' files of at most 200 rows each.
    An invoice's rows are never split across two parts."""
    groups = []
    for r in rows:
        key = (r.get("customer"), r.get("invoice"))
        if groups and groups[-1][0] == key:
            groups[-1][1].append(r)
        else:
            groups.append((key, [r]))
    parts, cur = [], []
    for _, g in groups:
        if cur and len(cur) + len(g) > MAX_ROWS:
            parts.append(cur)
            cur = []
        cur.extend(g)
    if cur:
        parts.append(cur)
    try:
        if len(parts) == 1:
            return fname, fill_template(tdata, parts[0])
        import io
        import zipfile
        stem = fname[:-5] if fname.lower().endswith(".xlsx") else fname
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for i, p in enumerate(parts, 1):
                z.writestr(f"{stem} part {i} of {len(parts)}.xlsx", fill_template(tdata, p))
        return f"{stem} ({len(parts)} files).zip", buf.getvalue()
    except TemplateError as e:
        raise ApiError(str(e))


def generate(bid, body):
    b, settings, lines, rows, warn, summary, tdata = prepare(bid, body)
    if summary["missing"]:
        raise ApiError(f"{summary['missing']} invoice(s) still need a CHEP size - choose it in the table first.")
    if not rows:
        if summary.get("already"):
            raise ApiError(f"All {summary['already']} CHEP invoice(s) in the ticked sheets were already sent in "
                           "earlier files (see History). Press 'Send again' on a line if one really must go again.")
        raise ApiError("Nothing to put in the template - no invoice in the ticked sheets goes in CHEPs.")
    remember_choices(lines)
    days = sorted({r["doc_date"] for r in rows if r["doc_date"]})
    label = days[-1].strftime("%d-%m-%Y") if days else datetime.now().strftime("%d-%m-%Y")
    fname = settings.get("file_name", "BulkTransfer Template {date}.xlsx").replace("{date}", label)
    fname, xlsx = package(tdata, rows, fname)
    con = get_db()
    cur = con.execute("INSERT INTO chep_runs(batch_id, created_at, file_name, doc_date, summary, rows, xlsx) "
                      "VALUES(?,?,?,?,?,?,?)",
                      (bid, datetime.now().isoformat(timespec="seconds"), fname,
                       days[-1].isoformat() if days else None,
                       json.dumps(dict(summary, source=b["name"], warnings=warn)),
                       json.dumps(_rows_json(rows)), xlsx))
    con.commit()
    return dict(run_id=cur.lastrowid, file_name=fname, summary=summary, warnings=warn)


# ---------------------------------------------------------------- combine
def combine(ids):
    """Several History files -> one template sheet (oldest Doc Date first).
    An invoice already taken from an earlier file is skipped, so a day made twice is not doubled."""
    ids = [int(i) for i in ids or []]
    if len(ids) < 2:
        raise ApiError("Tick at least two files to combine.")
    con = get_db()
    marks = ",".join("?" * len(ids))
    runs = [dict(r) for r in con.execute(
        f"SELECT id, file_name, doc_date, rows FROM chep_runs WHERE id IN ({marks})", ids).fetchall()]
    if len(runs) != len(ids):
        raise ApiError("Some of the ticked files are no longer in History - refresh the page.")
    runs.sort(key=lambda r: (r["doc_date"] or "", r["id"]))
    out, seen, skipped = [], {}, []
    for r in runs:
        taken_here = set()
        for row in json.loads(r["rows"] or "[]"):
            key = (row.get("customer"), row.get("invoice"))
            if key in seen and seen[key] != r["id"]:
                if key not in taken_here:
                    skipped.append(row.get("invoice"))
                    taken_here.add(key)
                continue
            seen[key] = r["id"]
            d = row.get("doc_date")
            out.append(dict(row, doc_date=date.fromisoformat(d) if d else None))
    if not out:
        raise ApiError("The ticked files have no rows.")
    _, tdata, _ = active_template()
    days = sorted({r["doc_date"] for r in out if r["doc_date"]})
    fmt = lambda d: d.strftime("%d-%m-%Y")  # noqa: E731
    label = (fmt(days[0]) if len(days) == 1 else f"{fmt(days[0])} to {fmt(days[-1])}") if days else "combined"
    fname, xlsx = package(tdata, out, f"BulkTransfer Template {label}.xlsx")
    note = f"{len(runs)} files, {len(out)} rows"
    if fname.endswith(".zip"):
        note += " - more than 200 rows, so split into separate files (upload each one on the CHEP portal)"
    if skipped:
        note += f"; {len(set(skipped))} invoice(s) were in two files and taken once: {', '.join(sorted(set(skipped))[:10])}"
    return fname, xlsx, note
