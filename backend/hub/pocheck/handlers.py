import urllib.parse
from datetime import datetime

from . import Response, route
from ..http import ApiError
from . import service


@route("GET", r"/api/files")
def files(req):
    return service.files()


@route("POST", r"/api/upload")
def upload(req):
    kind = req.arg("kind")
    name = urllib.parse.unquote(req.arg("name") or "upload")
    data = req._body_bytes
    if not data:
        raise ApiError("Empty file")
    try:
        return service.add_file(kind, name, data)
    except ValueError as e:
        raise ApiError(str(e))


@route("DELETE", r"/api/files")
def delete(req):
    service.remove(fid=req.arg("id") or None, kind=req.arg("kind") or None)
    return service.files()


@route("GET", r"/api/excel-check")
def excel_check(req):
    try:
        return service.excel_check()
    except ValueError as e:
        raise ApiError(str(e))


@route("GET", r"/api/price-changes")
def price_changes(req):
    try:
        return service.price_changes()
    except ValueError as e:
        raise ApiError(str(e))


@route("GET", r"/api/export")
def export(req):
    which = "excel" if req.arg("which") == "excel" else "changes"
    try:
        data = service.to_xlsx(which)
    except ValueError as e:
        raise ApiError(str(e))
    name = f"{'Excel_vs_PO' if which == 'excel' else 'PO_price_changes'}_{datetime.now():%d-%m-%Y}.xlsx"
    return Response(data, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
