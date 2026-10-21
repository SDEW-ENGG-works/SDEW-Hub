"""Hub pages: Today, search, invoice trail, part / PO / DR views, one drop box, open items, masters."""
import urllib.parse
from datetime import datetime

from .. import config
from ..db import get_db, log, one, rows
from ..http import ApiError, route
from ..services import insight
from ..services.router import route_file


@route("GET", r"/api/hub/overview")
def overview(req):
    d = insight.overview()
    d["db_mode"] = config.db_mode()
    return d


@route("GET", r"/api/hub/checks")
def checks(req):
    return insight.checks()


@route("GET", r"/api/hub/search")
def search(req):
    return insight.search(req.arg("q"))


@route("GET", r"/api/hub/invoice")
def invoice(req):
    no = req.arg("no").strip()
    if not no:
        raise ApiError("Type an invoice number")
    return insight.invoice_trail(no)


@route("GET", r"/api/hub/part")
def part(req):
    p = req.arg("part").strip()
    if not p:
        raise ApiError("Type a part number")
    return insight.part_view(p)


@route("GET", r"/api/hub/po")
def po(req):
    r = insight.po_view(req.arg("po").strip())
    if not r:
        raise ApiError("PO not found", 404)
    return r


@route("GET", r"/api/hub/dr")
def dr(req):
    return insight.dr_view(req.arg("dr"))


@route("POST", r"/api/hub/upload")
def upload(req):
    name = urllib.parse.unquote(req.arg("name", "upload"))
    if not req._body_bytes:
        raise ApiError("Empty file.")
    return route_file(name, req._body_bytes)


# ---- open items (follow-ups) ----
@route("GET", r"/api/hub/open-items")
def list_items(req):
    return rows("SELECT * FROM open_items ORDER BY status DESC, module, id")


@route("POST", r"/api/hub/open-items")
def add_item(req):
    b = req.json
    title = str(b.get("title") or "").strip()
    if not title:
        raise ApiError("Write what needs doing")
    mod = b.get("module") if b.get("module") in ("supp", "chep", "dqms", "grin", "pos", "hub", "cross") else "hub"
    con = get_db()
    con.execute("INSERT INTO open_items(module,title,detail,status,created_at) VALUES(?,?,?,?,?)",
                (mod, title[:200], str(b.get("detail") or "")[:1000], "open", datetime.now().isoformat(timespec="seconds")))
    con.commit()
    log(mod, "open item added", title)
    return dict(ok=True)


@route("PUT", r"/api/hub/open-items/(?P<id>\d+)")
def update_item(req):
    b = req.json
    it = one("SELECT * FROM open_items WHERE id=?", (int(req.params["id"]),))
    if not it:
        raise ApiError("Not found", 404)
    status = "done" if b.get("status") == "done" else "open"
    con = get_db()
    con.execute("UPDATE open_items SET status=?, done_at=?, detail=COALESCE(?, detail) WHERE id=?",
                (status, datetime.now().isoformat(timespec="seconds") if status == "done" else None,
                 b.get("detail"), it["id"]))
    con.commit()
    log(it["module"], "open item " + status, it["title"])
    return dict(ok=True)


# ---- masters: one read-only view of the settings every module keeps ----
@route("GET", r"/api/hub/masters")
def masters(req):
    from ..chep.services.defaults import load_settings as chep_settings
    from ..dqms.services.defaults import load_settings as dqms_settings
    from ..supp.services.defaults import load_settings as supp_settings
    s, c, d = supp_settings(), chep_settings(), dqms_settings()
    chep_cust = {p["code"]: p.get("customer", "") for p in c["plants"]}
    plants = []
    for p in s["plants"]:
        plants.append(dict(p, chep_customer=chep_cust.pop(p["code"], ""),
                           pos=one("SELECT COUNT(*) n FROM po_headers WHERE plant=?", (p["code"],))["n"]))
    for code, cust in chep_cust.items():
        plants.append(dict(code=code, chep_customer=cust, pos=0))
    return dict(plants=plants, crate_sizes=c["types"], chep_bp=c["bp_code"],
                part_corrections=s["part_corrections"], fixed_rates=s["overrides"],
                rate_pending_pos=s["rate_pending_pos"], price_dates=dict(old=s["old_date"], new=s["new_date"]),
                diff_basis=s["diff_basis"], reasons=d["reasons"], transporter=d["transporter"],
                counts=dict(pos=one("SELECT COUNT(*) n FROM po_headers")["n"],
                            po_items=one("SELECT COUNT(*) n FROM po_items")["n"],
                            parts_sized=one("SELECT COUNT(*) n FROM part_types")["n"],
                            typed_lines=one("SELECT COUNT(*) n FROM line_overrides")["n"]),
                env=_env_status())


def _env_status():
    env = config.read_env()
    has = lambda *k: all(env.get(x) for x in k)  # noqa: E731
    try:
        import playwright  # noqa: F401
        pw = True
    except ImportError:
        pw = False
    return dict(tafe_login=has("TAFE_USER", "TAFE_PASS"), leap_login=has("LEAP_USER", "LEAP_PASS"),
                password=has("APP_PASSWORD"), cloud=config.db_mode() == "cloud", playwright=pw)


@route("GET", r"/api/hub/activity")
def activity(req):
    return rows("SELECT * FROM activity ORDER BY id DESC LIMIT 200")
