import base64
import gzip
import urllib.parse

from . import route
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
