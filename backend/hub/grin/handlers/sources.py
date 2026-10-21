import urllib.parse
from datetime import date, timedelta

from .. import route
from ..db import rows
from ...http import ApiError
from ..services import status as st
from ..services import tally
from ..services.defaults import load_settings, plants
from ..services.ingest import ingest
from ..services.mailer import smtp_settings


@route("POST", r"/api/upload")
def upload(req):
    name = urllib.parse.unquote(req.arg("name", "upload"))
    if not req._body_bytes:
        raise ApiError("Empty file.")
    return ingest(name, req._body_bytes)


def _one(sql, args=()):
    r = rows(sql, args)
    return r[0] if r else {}


@route("GET", r"/api/sources")
def sources(req):
    from ...supp.services import grin_portal
    s = load_settings()
    parties = [p["party"] for p in plants()]
    ph = ",".join("?" * len(parties)) or "''"
    return dict(
        tally=dict(url=s["tally_url"], companies=s["tally_companies"],
                   **_one("SELECT COUNT(*) n, MIN(inv_date) first, MAX(inv_date) last, MAX(pulled_at) pulled "
                          "FROM gp_tally_invoices"),
                   status=tally.STATUS),
        sales=_one(f"SELECT COUNT(DISTINCT voucher) n, MIN(inv_date) first, MAX(inv_date) last FROM sales_lines "
                   f"WHERE party IN ({ph})", parties),
        grin=dict(**_one("SELECT COUNT(DISTINCT grin_no) n, COUNT(DISTINCT invoice_no) invoices, MIN(grin_date) first, "
                         "MAX(grin_date) last, MAX(updated_at) updated FROM grin_lines"),
                  portal=dict(available=grin_portal.available(), **grin_portal.STATUS)),
        payments=_one("SELECT COUNT(*) n, COUNT(DISTINCT pv) vouchers, MIN(pv_date) first, MAX(pv_date) last "
                      "FROM gp_pay_lines"),
        register=_one("SELECT COUNT(*) n, SUM(pv<>'') marked, MAX(inv_date) last, MAX(file) file, MAX(loaded_at) loaded "
                      "FROM gp_register"),
        files=rows("SELECT * FROM gp_pay_files ORDER BY id DESC LIMIT 50"),
        smtp=dict(ready=smtp_settings()["ready"], host=smtp_settings()["host"], sender=smtp_settings()["sender"]),
        dates=st.data_dates())


@route("POST", r"/api/tally/test")
def tally_test(req):
    url = (req.json.get("url") or load_settings()["tally_url"]).strip()
    try:
        names = tally.list_companies(url)
    except Exception as e:  # noqa: BLE001
        raise ApiError(f"Tally is not answering on {url}: {e}. Open TallyPrime and turn on F1 Help > Settings > "
                       f"Connectivity > Client/Server configuration: 'Both', port 9000.")
    return dict(url=url, companies=names)


@route("POST", r"/api/tally/pull")
def tally_pull(req):
    b = req.json
    s = load_settings()
    try:
        d2 = date.fromisoformat(b.get("to") or date.today().isoformat())
        d1 = date.fromisoformat(b.get("from") or (d2 - timedelta(days=45)).isoformat())
    except ValueError:
        raise ApiError("Dates must be yyyy-mm-dd")
    if d1 > d2:
        raise ApiError("From date is after To date")
    comps = b.get("companies") if b.get("companies") is not None else s["tally_companies"]
    if not tally.start(s["tally_url"], comps, d1, d2, {p["party"] for p in plants()}):
        raise ApiError("A Tally pull is already running")
    st.invalidate()
    return dict(started=True)


@route("GET", r"/api/tally/pull")
def tally_status(req):
    if not tally.STATUS["running"]:
        st.invalidate()
    return tally.STATUS
