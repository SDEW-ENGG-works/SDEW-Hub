import urllib.parse

from ..db import get_db, set_setting
from ..http import ApiError, Response, route
from ..services import store
from ..services.defaults import DEFAULT_SETTINGS, load_settings

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@route("GET", r"/api/settings")
def get_settings(req):
    return dict(settings=load_settings(), template=store.template_summary())


@route("PUT", r"/api/settings")
def put_settings(req):
    body = req.json
    s = load_settings()
    if "bp_code" in body:
        v = str(body["bp_code"]).strip()
        if not v:
            raise ApiError("BP Code is needed")
        s["bp_code"] = v
    if "file_name" in body:
        v = str(body["file_name"]).strip() or DEFAULT_SETTINGS["file_name"]
        s["file_name"] = v if v.lower().endswith(".xlsx") else v + ".xlsx"
    if "plants" in body:
        out = []
        for p in body["plants"]:
            code = str(p.get("code", "")).strip().upper()
            if code:
                out.append(dict(code=code, customer=str(p.get("customer", "")).strip(),
                                note=str(p.get("note", "")).strip()[:80]))
        s["plants"] = out
    if "types" in body:
        out, codes = [], set()
        for t in body["types"]:
            code = str(t.get("code", "")).strip()
            if not code:
                continue
            if code in codes:
                raise ApiError(f"CHEP size {code} is listed twice")
            codes.add(code)
            out.append(dict(code=code, names=str(t.get("names", "")).strip(),
                            pallet=str(t.get("pallet", "")).strip().upper(), lid=str(t.get("lid", "")).strip().upper()))
        s["types"] = out
    set_setting("app", {k: s[k] for k in DEFAULT_SETTINGS})
    return dict(settings=s)


@route("POST", r"/api/template")
def upload_template(req):
    name = urllib.parse.unquote(req.arg("name", "BulkTransfer Template.xlsx"))
    if not req._body_bytes:
        raise ApiError("Empty file.")
    store.save_template(name, req._body_bytes)
    return store.template_summary()


@route("GET", r"/api/template/file")
def template_file(req):
    name, data, _ = store.active_template()
    return Response(bytes(data), content_type=XLSX, headers={
        "Content-Disposition": "attachment; filename=\"BulkTransfer Template.xlsx\""})


@route("POST", r"/api/settings/reset-data")
def reset_data(req):
    what = req.json.get("what")
    tables = {"parts": ["part_types"], "runs": ["chep_runs"], "batches": ["chep_runs", "batches"],
              "template": ["templates"]}.get(what)
    if not tables:
        raise ApiError("Nothing to clear")
    con = get_db()
    for t in tables:
        con.execute(f"DELETE FROM {t}")
    con.commit()
    return dict(ok=True)
