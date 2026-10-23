"""Monthly payment report: /api/grin/monthly?month=yyyy-mm and its Excel."""
import io
from datetime import datetime

from .. import Response, route
from ...http import ApiError
from ..services import monthly as mo


def _month(req):
    m = req.arg("month").strip()
    if m and (len(m) != 7 or m[4] != "-" or not (m[:4] + m[5:]).isdigit()):
        raise ApiError("month must be yyyy-mm")
    return m or None


@route("GET", r"/api/monthly")
def monthly(req):
    r = mo.report(_month(req))
    if req.arg("full") != "1":
        r["invoices_total"] = len(r["invoices"])
        r["invoices"] = r["invoices"][:3000]
    return r


@route("GET", r"/api/monthly/export")
def monthly_export(req):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    r = mo.report(_month(req))
    s = r["summary"]
    wb = openpyxl.Workbook()
    hfill, hfont, bold = PatternFill("solid", fgColor="1E293B"), Font(bold=True, color="FFFFFF"), Font(bold=True)
    money = "#,##0.00"

    def d(v):
        try:
            return datetime.strptime(v[:10], "%Y-%m-%d") if v else None
        except (ValueError, TypeError):
            return v

    def sheet(ws, head, data, widths, money_cols=(), date_cols=()):
        ws.append(head)
        for c in ws[ws.max_row]:
            c.fill, c.font = hfill, hfont
        start = ws.max_row
        for row in data:
            ws.append([d(v) if i in date_cols else v for i, v in enumerate(row)])
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        for row in ws.iter_rows(min_row=start + 1, max_row=ws.max_row):
            for i, c in enumerate(row):
                if i in money_cols:
                    c.number_format = money
                elif i in date_cols:
                    c.number_format = "dd-mm-yyyy"
        if data:
            ws.auto_filter.ref = f"A{start}:{get_column_letter(len(head))}{ws.max_row}"
        ws.freeze_panes = f"A{start + 1}"

    # Summary
    ws = wb.active
    ws.title = "Summary"
    ws.append([f"TAFE payments - {r['label']}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"{r['from_']} to {r['to']} · source: {s['source'] or '-'} · made {datetime.now():%d-%m-%Y %H:%M}"])
    ws.append([])
    lines = [("Payment vouchers", s["payments"], False), ("Invoices paid", s["invoices"], False),
             ("Invoices paid (gross)", s["gross"], True), ("Less: debit notes (ZK)", -s["debit_note"], True),
             ("Less: cash discount (KG)", -s["discount"], True), ("Less: other deductions", -s["other"], True),
             ("Net received", s["net"], True), ("", None, False),
             ("Avg days invoice -> payment", r["speed"]["avg_inv"], False),
             ("Avg days GRIN -> payment", r["speed"]["avg_grin"], False),
             (f"Paid on time (within {r['credit_days']} days of GRIN)", r["speed"]["on_time_n"], False),
             ("Paid late", r["speed"]["late_n"], False), ("", None, False),
             ("Billed this month (invoices)", r["billed"]["n"], False), ("Billed this month (value)", r["billed"]["value"], True),
             ("  of that paid within the month", r["billed"]["paid_same_month"], True), ("", None, False),
             ("Pending at month end (invoices)", r["pending"]["n"], False),
             ("Pending at month end (value)", r["pending"]["value"], True),
             ("  overdue", r["pending"]["overdue_value"], True), ("  GRINed, not yet due", r["pending"]["due_value"], True),
             ("  not GRINed", r["pending"]["ng_value"], True)]
    for label, v, is_money in lines:
        ws.append([label, v])
        if is_money:
            ws.cell(ws.max_row, 2).number_format = money
        if label == "Net received":
            ws.cell(ws.max_row, 1).font = ws.cell(ws.max_row, 2).font = bold
    for n in r["notes"]:
        ws.append([])
        ws.append([n])
        ws.cell(ws.max_row, 1).alignment = Alignment(wrap_text=False)
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 18

    sheet(wb.create_sheet("Vouchers"), ["Voucher (PV)", "Date", "Source", "Invoices", "Gross", "Debit notes",
                                        "Cash discount", "Other", "Net received"],
          [[v["pv"], v["pv_date"], v["source"], v["invoices"], v["gross"], v["debit_note"], v["discount"], v["other"],
            v["net"]] for v in r["vouchers"]], [15, 12, 16, 9, 15, 13, 13, 11, 15], (4, 5, 6, 7, 8), (1,))
    sheet(wb.create_sheet("By plant"), ["Plant", "Invoices", "Vouchers", "Gross", "Debit notes", "Net"],
          [[p["plant"], p["invoices"], p["payments"], p["gross"], p["deductions"], p["net"]] for p in r["by_plant"]]
          + ([["Cash discount (whole voucher)", None, None, None, s["discount"], -s["discount"]]] if s["discount"] else []),
          [30, 10, 10, 16, 14, 16], (3, 4, 5))
    sheet(wb.create_sheet("Invoices paid"), ["Invoice No", "Invoice Date", "Plant", "Invoice Value", "Paid", "Voucher",
                                             "Paid On", "GRIN Date", "Days from invoice", "Days from GRIN",
                                             "Late by (days)", "Source"],
          [[i["inv_no"], i["inv_date"], i["plant"], i["amount"], i["paid"], i["pv"], i["pv_date"], i["grin_date"],
            i["days_inv"], i["days_grin"], i["late_days"] or None, i["source"]] for i in r["invoices"]],
          [14, 12, 10, 14, 14, 14, 12, 12, 10, 10, 10, 16], (3, 4), (1, 6, 7))
    sheet(wb.create_sheet("Deductions"), ["Voucher", "Date", "Kind", "Type", "Reference", "TAFE doc", "Plant", "Amount"],
          [[x["pv"], x["pv_date"], x["kind"], x["doc_type"], x["ref"], x["ref_doc"], x["plant"], x["amount"]]
           for x in r["deductions"]], [14, 12, 16, 6, 18, 14, 10, 14], (7,), (1,))
    sheet(wb.create_sheet("Pending at month end"), ["Invoice No", "Invoice Date", "Plant", "Value", "Where", "GRIN Date",
                                                    "Due Date", "Overdue by (days)", "Paid later on"],
          [[p["inv_no"], p["inv_date"], p["plant"], p["amount"], p["kind"], p["grin_date"], p["due_date"],
            p["late_days"] or None, p["paid_on"]] for p in r["pending_list"]],
          [14, 12, 10, 14, 13, 12, 12, 10, 12], (3,), (1, 5, 6, 8))
    sheet(wb.create_sheet("Month by month"), ["Month", "Vouchers", "Invoices paid", "Gross", "Deductions", "Net received",
                                              "Invoices billed", "Billed value", "Pending at month end",
                                              "Overdue at month end", "Source"],
          [[t["month"], t["payments"], t["invoices"], t["gross"], t["deductions"], t["net"], t["billed_n"], t["billed"],
            t["pending"], t["overdue"], t["source"]] for t in r["trend"]],
          [10, 10, 12, 16, 13, 16, 12, 16, 16, 16, 16], (3, 4, 5, 7, 8, 9))
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="TAFE_Payments_{r["month"]}.xlsx"'})
