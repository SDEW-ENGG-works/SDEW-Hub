from datetime import date

from .. import route
from ..db import set_setting
from ...http import ApiError
from ..services import status as st
from ..services.defaults import DEFAULT_SETTINGS, load_settings
from ..services.mailer import smtp_settings


@route("GET", r"/api/settings")
def get_settings(req):
    m = smtp_settings()
    return dict(settings=load_settings(), defaults=DEFAULT_SETTINGS,
                smtp=dict(ready=m["ready"], host=m["host"], port=m["port"], sender=m["sender"]))


@route("PUT", r"/api/settings")
def put_settings(req):
    b = req.json
    s = load_settings()
    for k in ("wait_days", "credit_days", "resend_days", "escalate_after"):
        if k in b:
            try:
                v = int(b[k])
            except (TypeError, ValueError):
                raise ApiError(f"{k} must be a whole number")
            if v < 0 or v > 365:
                raise ApiError(f"{k} must be 0-365")
            s[k] = v
    if "from_date" in b:
        try:
            date.fromisoformat(b["from_date"])
        except ValueError:
            raise ApiError("from_date must be a date")
        s["from_date"] = b["from_date"]
    for k in ("escalate_cc", "test_to", "mail_subject", "mail_intro", "signature", "tally_url"):
        if k in b:
            s[k] = str(b[k] or "").strip() if k not in ("mail_intro", "signature") else str(b[k] or "")
    if s["test_to"] and "@" not in s["test_to"]:
        raise ApiError("Test address looks wrong")
    if "track_plants_without_grin" in b:
        s["track_plants_without_grin"] = bool(b["track_plants_without_grin"])
    if "ignore_doc_types" in b:
        s["ignore_doc_types"] = [t.strip().upper() for t in b["ignore_doc_types"] if t and t.strip()]
    if "tally_companies" in b:
        s["tally_companies"] = [dict(name=str(c.get("name", "")).strip(), location=str(c.get("location", "")).strip())
                                for c in b["tally_companies"] if str(c.get("name", "")).strip()]
    for k in ("mail_subject", "mail_intro"):
        try:
            s[k].format(count=1, plant="X", name="Y")
        except (KeyError, IndexError, ValueError):
            raise ApiError(f"{k}: only {{count}}, {{plant}} and {{name}} can be used in braces")
    set_setting("app", s)
    st.invalidate()
    return dict(settings=s)
