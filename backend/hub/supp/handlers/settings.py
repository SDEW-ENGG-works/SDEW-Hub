from datetime import date

from ..db import get_db, set_setting
from ..http import ApiError, route
from ..services.defaults import DEFAULT_SETTINGS, load_settings
from ..services.norm import part_key
from .. import config


@route("GET", r"/api/settings")
def get_settings(req):
    env = config.read_env()
    return dict(settings=load_settings(), tafe_login=bool(env.get("TAFE_USER") and env.get("TAFE_PASS")),
                tafe_user=env.get("TAFE_USER", ""))


@route("PUT", r"/api/settings")
def put_settings(req):
    body = req.json
    s = load_settings()
    for k in ("old_date", "new_date"):
        if k in body:
            try:
                date.fromisoformat(body[k])
            except ValueError:
                raise ApiError(f"{k} must be a date")
            s[k] = body[k]
    if "diff_basis" in body:
        if body["diff_basis"] not in ("po", "billed"):
            raise ApiError("diff_basis must be po or billed")
        s["diff_basis"] = body["diff_basis"]
    for k in ("remove_billed_at_revised", "exclude_old_date_invoices"):
        if k in body:
            s[k] = bool(body[k])
    if "overrides" in body:
        out = []
        for o in body["overrides"]:
            p = part_key(o.get("part"))
            if not p:
                continue
            try:
                ex = o.get("existing")
                out.append(dict(part=p, revised=round(float(o.get("revised")), 2),
                                existing=round(float(ex), 2) if ex not in (None, "") else None,
                                note=str(o.get("note", ""))[:120]))
            except (TypeError, ValueError):
                raise ApiError(f"Reversed Rate for {p} is not a number")
        s["overrides"] = out
    if "part_corrections" in body:
        out = []
        for c in body["part_corrections"]:
            f, t = part_key(c.get("from")), part_key(c.get("to"))
            if f and t and f != t:
                out.append(dict(plant=str(c.get("plant", "")).strip(), **{"from": f, "to": t},
                                note=str(c.get("note", ""))[:120]))
        s["part_corrections"] = out
    if "rate_pending_pos" in body:
        v = body["rate_pending_pos"]
        if isinstance(v, str):
            v = v.replace(",", " ").split()
        s["rate_pending_pos"] = sorted({str(x).strip() for x in v if str(x).strip()})
    if "plants" in body:
        out = []
        for p in body["plants"]:
            if not (p.get("code") or "").strip():
                continue
            out.append({k: str(p.get(k, "")).strip() for k in ("code", "party", "grin_plant", "main_po", "bill_to")})
        s["plants"] = out
    set_setting("app", {k: s[k] for k in DEFAULT_SETTINGS})
    return dict(settings=s)


@route("POST", r"/api/settings/reset-data")
def reset_data(req):
    what = req.json.get("what")
    tables = {"sales": ["sales_lines", "grn_sheet"], "grin": ["grin_lines"], "pos": ["po_items", "po_headers"],
              "runs": ["run_lines", "bill_runs"]}.get(what)
    if not tables:
        raise ApiError("Nothing to clear")
    con = get_db()
    for t in tables:
        con.execute(f"DELETE FROM {t}")
    con.commit()
    return dict(ok=True)
