from ..db import get_db, set_setting
from .. import route
from ...http import ApiError
from ..services.defaults import DEFAULT_SETTINGS, load_settings


@route("GET", r"/api/settings")
def get_settings(req):
    return dict(settings=load_settings())


@route("PUT", r"/api/settings")
def put_settings(req):
    body = req.json
    s = load_settings()
    for k in ("mark_credit_debit", "mark_amount_differs", "fill_rows"):
        if k in body:
            s[k] = bool(body[k])
    for k in ("min_ratio", "max_ratio"):
        if k in body:
            try:
                s[k] = round(float(body[k]), 4)
            except (TypeError, ValueError):
                raise ApiError(f"{k} must be a number")
    if s["min_ratio"] >= s["max_ratio"]:
        raise ApiError("Lowest % must be below highest %")
    if "fill_color" in body:
        c = str(body["fill_color"]).strip().lstrip("#").upper()
        if len(c) != 6 or any(ch not in "0123456789ABCDEF" for ch in c):
            raise ApiError("Colour must be like 92D050")
        s["fill_color"] = c
    if "ignore_doc_types" in body:
        v = body["ignore_doc_types"]
        if isinstance(v, str):
            v = v.replace(",", " ").split()
        s["ignore_doc_types"] = sorted({str(x).strip().upper() for x in v if str(x).strip()})
    set_setting("app", {k: s[k] for k in DEFAULT_SETTINGS})
    return dict(settings=s)


@route("POST", r"/api/settings/reset-data")
def reset_data(req):
    what = req.json.get("what")
    tables = {"payments": ["pm_pay_lines", "pm_vouchers"], "runs": ["pm_run_lines", "pm_runs"],
              "sales": ["ps_lines", "ps_actions", "ps_runs"]}.get(what)
    if not tables:
        raise ApiError("Nothing to clear")
    con = get_db()
    for t in tables:
        con.execute(f"DELETE FROM {t}")
    con.commit()
    return dict(ok=True)
