import urllib.parse

from .. import Response, route
from ..db import get_db, rows
from ...http import ApiError
from ..services import mailer
from ..services import status as st


def _as_of(req, body=None):
    return ((body or {}).get("as_of") or req.arg("as_of") or "").strip() or None


@route("GET", r"/api/mails/plan")
def plan(req):
    return mailer.plan(_as_of(req))


@route("POST", r"/api/mails/send")
def send(req):
    b = req.json
    keys = b.get("keys")
    p = mailer.plan(_as_of(req, b), inv_keys=set(b["inv_keys"]) if b.get("inv_keys") else None)
    drafts = [d for d in p["drafts"] if keys is None or d["key"] in keys]
    if not drafts:
        raise ApiError("Nothing to send.")
    try:
        return dict(results=mailer.send(drafts), test_to=p["test_to"])
    except RuntimeError as e:
        raise ApiError(str(e))


@route("GET", r"/api/mails/eml")
def eml(req):
    key = urllib.parse.unquote(req.arg("key"))
    p = mailer.plan(_as_of(req))
    d = next((x for x in p["drafts"] if x["key"] == key), None)
    if not d:
        raise ApiError("That mail is not in the list any more.")
    name = f"GRIN_reminder_{d['plant']}_{(d['buyer'] or 'buyer').replace(' ', '_')}.eml"
    return Response(mailer.eml(d), content_type="message/rfc822",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@route("GET", r"/api/mails/history")
def history(req):
    return mailer.history()


@route("POST", r"/api/mails/(?P<id>\d+)/sent")
def mark_sent(req):
    try:
        mailer.mark_sent(int(req.params["id"]))
    except ValueError as e:
        raise ApiError(str(e), 404)
    return dict(ok=True)


@route("GET", r"/api/buyers")
def buyers(req):
    data = st.build()
    pending = {}
    for r in data["rows"]:
        if r["status"] == st.NOT_GRINED:
            pending[r["buyer_id"] or f"plant:{r['plant']}"] = pending.get(r["buyer_id"] or f"plant:{r['plant']}", 0) + 1
    out = st.buyers()
    for b in out:
        b["pending"] = pending.get(b["id"], 0)
    unassigned = [dict(plant=k.split(":", 1)[1], pending=v) for k, v in pending.items() if isinstance(k, str)]
    from ..services.defaults import plants
    return dict(buyers=out, unassigned=unassigned,
                plants=[dict(code=p["code"], party=p["party"], grin_plant=p.get("grin_plant", "")) for p in plants()])


@route("POST", r"/api/buyers")
def save_buyer(req):
    b = req.json
    email = (b.get("email") or "").strip()
    if not (b.get("plant") or b.get("po_no")):
        raise ApiError("Give a plant or a PO number")
    if email and "@" not in email:
        raise ApiError("E-mail address looks wrong")
    vals = ((b.get("plant") or "").strip().upper(), (b.get("po_no") or "").strip(), (b.get("name") or "").strip(),
            email, (b.get("cc") or "").strip(), (b.get("note") or "").strip())
    con = get_db()
    if b.get("id"):
        con.execute("UPDATE gp_buyers SET plant=?, po_no=?, name=?, email=?, cc=?, note=? WHERE id=?", (*vals, int(b["id"])))
        bid = int(b["id"])
    else:
        bid = con.execute("INSERT INTO gp_buyers(plant, po_no, name, email, cc, note) VALUES(?,?,?,?,?,?)", vals).lastrowid
    con.commit()
    st.invalidate()
    return dict(id=bid)


@route("DELETE", r"/api/buyers/(?P<id>\d+)")
def delete_buyer(req):
    con = get_db()
    con.execute("DELETE FROM gp_buyers WHERE id=?", (int(req.params["id"]),))
    con.commit()
    st.invalidate()
    return dict(ok=True)


@route("GET", r"/api/mails/count")
def count(req):
    return dict(n=len(rows("SELECT id FROM gp_mails")))
