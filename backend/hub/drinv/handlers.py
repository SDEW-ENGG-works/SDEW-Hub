import base64
import gzip
import urllib.parse

from . import Response, route
from .. import config as hubconfig
from ..http import ApiError
from . import service


def _ids(req):
    ids = (req.json or {}).get("ids") or []
    if not ids:
        raise ApiError("Pick at least one invoice")
    return [int(i) for i in ids]


@route("GET", r"/api/drafts")
def drafts(req):
    if req.flag("recheck"):
        service.recheck()
    return service.listing(req.arg("status"))


@route("POST", r"/api/upload")
def upload(req):
    name = urllib.parse.unquote(req.arg("name") or "dr.pdf")
    data = req._body_bytes
    if not data:
        raise ApiError("Empty file")
    try:
        return service.add_pdf(name, data, req.arg("date") or None)
    except ValueError as e:
        raise ApiError(str(e))
    except Exception as e:  # noqa: BLE001
        raise ApiError(f"Could not read {name}: {e}")


@route("POST", r"/api/drafts/(?P<id>\d+)")
def edit(req):
    try:
        return service.update(int(req.params["id"]), req.json or {})
    except ValueError as e:
        raise ApiError(str(e))


@route("POST", r"/api/number")
def number(req):
    try:
        service.number_from((req.json or {}).get("start"), _ids(req))
    except ValueError as e:
        raise ApiError(str(e))
    return service.listing()


@route("POST", r"/api/verify")
def verify(req):
    b = req.json or {}
    bad = service.verify(_ids(req), on=b.get("on", True) is not False, force=bool(b.get("force")))
    out = service.listing()
    out["not_verified"] = bad
    return out


@route("POST", r"/api/delete")
def delete(req):
    service.remove(_ids(req))
    return service.listing()


@route("GET", r"/api/history")
def history(req):
    return service.history_log(int(req.arg("limit") or 200))


@route("POST", r"/api/config")
def save_config(req):
    service.save_config(req.json or {})
    return service.public_config()


# ---------------------------------------------------------------- Tally (browser -> Tally bridge, or this PC's server)
@route("GET", r"/api/learn-request")
def learn_request(req):
    return dict(requests=service.learn_request())


@route("POST", r"/api/learn")
def learn(req):
    b = req.json or {}
    text = b.get("text") or ""
    if b.get("gz"):
        text = gzip.decompress(base64.b64decode(b["gz"])).decode("utf-8", errors="replace")
    return service.learn(text, service.config().get("company", ""))


@route("POST", r"/api/learn-file")
def learn_file(req):
    """A voucher exported from Tally by hand (Alt+E > Export > XML) -> the invoice format, like Learn from Tally."""
    raw = req._body_bytes or b""
    if not raw:
        raise ApiError("Empty file")
    from ..grin.services.tally import decode
    return service.learn(decode(raw), "file " + urllib.parse.unquote(req.arg("name") or ""))


@route("POST", r"/api/send-plan")
def send_plan(req):
    try:
        return service.send_plan(_ids(req))
    except ValueError as e:
        raise ApiError(str(e))


@route("POST", r"/api/tally-result")
def tally_result(req):
    b = req.json or {}
    return service.tally_result(int(b.get("id")), b.get("text") or "")


@route("POST", r"/api/tally")
def tally_proxy(req):
    """The PC hub (localhost:8050) talks to Tally itself; the website goes through the Tally bridge."""
    if hubconfig.ON_VERCEL:
        raise ApiError("On the website Tally is reached through the Tally bridge of your computer")
    from ..grin.services import tally
    from ..grin.services.defaults import load_settings
    try:
        return dict(text=tally.post(load_settings()["tally_url"], (req.json or {}).get("xml") or "", timeout=120))
    except Exception as e:  # noqa: BLE001
        raise ApiError(f"Tally is not answering: {e}")


# ---------------------------------------------------------------- Read Tally structure
@route("POST", r"/api/structure-plan")
def structure_plan(req):
    nos = (req.json or {}).get("nos")
    if not nos:
        nos = service.structure_defaults()
    return dict(service.structure_plan(nos), nos=nos)


@route("POST", r"/api/structure-save")
def structure_save(req):
    b = req.json or {}
    text = b.get("text") or ""
    if b.get("gz"):
        text = gzip.decompress(base64.b64decode(b["gz"])).decode("utf-8", errors="replace")
    return service.structure_save(b.get("kind") or "", b.get("ref") or "", text, b.get("want") or [])


@route("GET", r"/api/structure")
def structure_list(req):
    return dict(samples=service.samples(), defaults=service.structure_defaults())


@route("GET", r"/api/structure-download")
def structure_download(req):
    ids = [int(x) for x in (req.arg("ids") or "").split(",") if x.strip().isdigit()]
    body = service.samples_text(ids or None).encode("utf-8")
    return Response(body, content_type="text/xml; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="tally_structure.xml"'})


# ---------------------------------------------------------------- Delivery challans from Tally (Admin)
@route("POST", r"/api/dc/plan")
def dc_plan(req):
    from datetime import date
    from . import dc
    b = req.json or {}
    try:
        d2 = date.fromisoformat(b.get("to") or date.today().isoformat())
        d1 = date.fromisoformat(b.get("from") or "2026-04-01")
    except ValueError:
        raise ApiError("Dates must be yyyy-mm-dd")
    if d1 > d2:
        raise ApiError("From date is after To date")
    return dict(chunks=dc.plan(service.config().get("company", ""), d1, d2))


@route("POST", r"/api/dc/save")
def dc_save(req):
    from . import dc
    b = req.json or {}
    text = b.get("text") or ""
    if b.get("gz"):
        text = gzip.decompress(base64.b64decode(b["gz"])).decode("utf-8", errors="replace")
    r = dc.save(text, b.get("from") or "", b.get("to") or "")
    if r.get("ok"):
        service.log_event("Pulled DC from Tally", f"{b.get('from')} to {b.get('to')}: {r.get('dcs', 0)} DC(s)")
    return r


@route("GET", r"/api/dc")
def dc_list(req):
    from . import dc
    return dc.listing(req.arg("q") or "", int(req.arg("limit") or 300))


# ---------------------------------------------------------------- invoice numbers from Tally
@route("GET", r"/api/numbers-request")
def numbers_request(req):
    return dict(xml=service.numbers_request())


def _text(b):
    text = b.get("text") or ""
    if b.get("gz"):
        text = gzip.decompress(base64.b64decode(b["gz"])).decode("utf-8", errors="replace")
    return text


@route("POST", r"/api/tally-next")
def tally_next(req):
    """Tally's answer -> its last invoice number and the next one (for the 'Number from' box)."""
    try:
        t = service.tally_last(_text(req.json or {}))
    except ValueError as e:
        raise ApiError(str(e))
    return dict(last=t["last"], next=t["next"])


@route("POST", r"/api/assign-numbers")
def assign_numbers(req):
    b = req.json or {}
    try:
        r = service.assign_from_tally([int(i) for i in (b.get("ids") or [])], _text(b))
    except ValueError as e:
        raise ApiError(str(e))
    return r
