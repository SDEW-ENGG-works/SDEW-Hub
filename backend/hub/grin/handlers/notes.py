"""Debit / credit notes from TAFE Channel: fetch, list, lines and Excel.  /api/grin/notes..."""
import io
from datetime import date, datetime, timedelta

from .. import Response, route
from ... import config
from ...http import ApiError
from ...services import pc_jobs
from ..services import notes
from ..services import notes_portal as npo


def _dates(b):
    try:
        d2 = date.fromisoformat(b.get("to") or date.today().isoformat())
        d1 = date.fromisoformat(b.get("from") or (d2 - timedelta(days=60)).isoformat())
    except ValueError:
        raise ApiError("Dates must be yyyy-mm-dd")
    if d1 > d2:
        raise ApiError("From date is after To date")
    return d1, d2


@route("POST", r"/api/notes/fetch")
def notes_fetch(req):
    d1, d2 = _dates(req.json)
    if npo.STATUS["running"]:
        raise ApiError("Already fetching debit / credit notes - wait for it to finish")
    if not config.ON_VERCEL:                          # the PC: everything in the background, the page polls
        npo.start(d1, d2)
        return dict(npo.STATUS, done=False)
    st_ = dict(npo.run(d1, d2, budget=45))            # the website: ~45 s per call, the page calls again (more=True)
    if st_["error"] and npo.network_problem(st_["error"]):
        a = pc_jobs.agent_info()
        if a and a["online"]:
            q = pc_jobs.queue("notes_fetch", {"from": d1.isoformat(), "to": d2.isoformat()})
            q["log"] = st_["log"] + ["TAFE Channel did not answer this website - asking the SDEW PC instead"] + q["log"]
            return dict(q, queued=True, done=False)
    return dict(st_, done=not st_.get("more"))


@route("GET", r"/api/notes/fetch")
def notes_fetch_status(req):
    if config.ON_VERCEL:
        j = pc_jobs.status("notes_fetch")
        if j.get("running") or (j.get("started") or "") > (npo.STATUS.get("started") or ""):
            return j
    return npo.STATUS


@route("GET", r"/api/notes")
def notes_list(req):
    return notes.summary(req.arg("from"), req.arg("to"))


@route("GET", r"/api/notes/lines")
def notes_lines(req):
    out = notes.lines_for(req.arg("kind"), req.arg("q").strip(), req.arg("from"), req.arg("to"),
                          limit=min(int(req.arg("limit", "1500") or 1500), 20000))
    return dict(rows=out, total=len(out))


@route("GET", r"/api/notes/export")
def notes_export(req):
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    d1, d2 = req.arg("from"), req.arg("to")
    s = notes.summary(d1, d2)
    wb = openpyxl.Workbook()
    hfill, hfont = PatternFill("solid", fgColor="1E293B"), Font(bold=True, color="FFFFFF")

    def sheet(ws, head, data, widths, money=()):
        ws.append(head)
        for c in ws[1]:
            c.fill, c.font = hfill, hfont
        for r in data:
            ws.append(r)
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        for row in ws.iter_rows(min_row=2):
            for i, c in enumerate(row):
                if i in money:
                    c.number_format = "#,##0.00"
        ws.freeze_panes = "A2"
        if data:
            ws.auto_filter.ref = f"A1:{get_column_letter(len(head))}{len(data) + 1}"

    ws = wb.active
    ws.title = "Summary"
    kinds = sorted(s["kinds"])
    sheet(ws, ["Month"] + [f"{k} (Rs)" for k in kinds] + ["Total (Rs)"],
          [[m["month"]] + [m["kinds"].get(k, {}).get("amount") for k in kinds] + [m["total"]] for m in s["months"]],
          [10] + [18] * (len(kinds) + 1), money=tuple(range(1, len(kinds) + 2)))
    sheet(wb.create_sheet("Documents"), ["Document No", "Type", "What", "Kind", "Date", "GRIN Date", "Plant", "Reason",
                                         "Amount (Rs)", "Lines", "Deducted in PV", "PV date"],
          [[d["doc_no"], d["doc_type"], d["type_label"], d["kind"], d["doc_date"], d["grin_date"], d["plant"], d["reason"],
            d["amount"], d["lines"], d["pv"], d["pv_date"]] for d in s["docs"]],
          [13, 6, 24, 16, 11, 11, 8, 26, 14, 7, 14, 11], money=(8,))
    lines = notes.lines_for("", "", d1, d2, limit=200000)
    sheet(wb.create_sheet("Lines"), ["Document No", "Type", "Kind", "Doc date", "Plant", "Our invoice", "Invoice date",
                                     "GRIN No", "GRIN date", "Part", "Description", "Qty", "PO No", "Bill rate",
                                     "PO rate", "Rate diff", "Basic (Rs)", "GST (Rs)", "Net (Rs)", "Days",
                                     "Rejection ref", "Rejection doc", "Reason"],
          [[r["doc_no"], r["doc_type"], r["kind"], r["doc_date"], r["plant"] or r["doc_plant"], r["inv_raw"], r["inv_date"],
            r["grn_no"], r["grn_date"], r["part"], r["part_desc"], r["qty"], r["po_no"], r["bill_rate"], r["po_rate"],
            r["diff_rate"], r["basic"], r["gst"], r["net"], r["days"], r["ref_no"], r["rej_doc"], r["reason"]]
           for r in lines],
          [13, 6, 15, 11, 7, 13, 11, 13, 11, 14, 26, 8, 12, 10, 10, 9, 12, 10, 12, 6, 13, 13, 22], money=(13, 14, 15, 16, 17, 18))
    buf = io.BytesIO()
    wb.save(buf)
    name = f"TAFE_Debit_Credit_Notes_{datetime.now():%Y%m%d}.xlsx"
    return Response(buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
