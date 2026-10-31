from ..db import get_db, set_setting
from ..http import ApiError, route
from ..services.defaults import DEFAULT_SETTINGS, load_settings


@route("GET", r"/api/settings")
def get_settings(req):
    return dict(settings=load_settings())


@route("PUT", r"/api/settings")
def put_settings(req):
    body = req.json
    s = load_settings()
    if "transporter" in body:
        v = str(body["transporter"]).strip().upper()
        if not v:
            raise ApiError("Transporter is needed")
        s["transporter"] = v
    for k in ("batch_applicable", "batch_considerable"):
        if k in body:
            s[k] = "NO" if str(body[k]).strip().upper() == "NO" else "YES"
    if "invoice_unit" in body:
        s["invoice_unit"] = "one" if body["invoice_unit"] == "one" else "packages"
    if "batch_order" in body:
        s["batch_order"] = "newest" if body["batch_order"] == "newest" else "oldest"
    if "reasons" in body:
        s["reasons"] = [str(x).strip() for x in body["reasons"] if str(x).strip()] or DEFAULT_SETTINGS["reasons"]
    if "file_name" in body:
        v = str(body["file_name"]).strip() or DEFAULT_SETTINGS["file_name"]
        s["file_name"] = v if v.lower().endswith(".csv") else v + ".csv"
    if body.get("reset_header"):
        s["header"] = DEFAULT_SETTINGS["header"]
    set_setting("app", {k: s[k] for k in DEFAULT_SETTINGS})
    return dict(settings=s)


@route("POST", r"/api/settings/reset-data")
def reset_data(req):
    what = req.json.get("what")
    tables = {"invoices": ["invoices", "portal_status"], "runs": ["dqms_runs"], "report": ["dqms_batches"],
              "typed": ["line_overrides"],
              # "Start fresh" on the Create page: empty page, History / POs / settings kept
              "fresh": ["invoices", "portal_status", "dqms_batches"]}.get(what)
    if not tables:
        raise ApiError("Nothing to clear")
    if what != "fresh":         # "Start fresh" on the Create page is daily work - the rest is admin only
        _admin_only(req)
    con = get_db()
    from ...services.safety import before_wipe
    before_wipe("dqms", what, tables, con, extra_settings=("dqms_report", "dqms.dqms_report"))    # copy kept first - Admin > Cleared data > Put back
    for t in tables:
        con.execute(f"DELETE FROM {t}")
    if what == "runs":
        con.execute("UPDATE invoices SET run_id=NULL")
    if what in ("report", "fresh"):
        con.execute("DELETE FROM settings WHERE key='dqms.dqms_report'")
    con.commit()
    return dict(ok=True)


def _admin_only(req):
    from ... import auth
    who = auth.current(req.cookie)
    if not who or not who.get("admin"):
        raise ApiError("Only the admin can clear data. Ask the admin - a copy is kept and can be put back.", 403)
