"""Admin page API: users and the pages each user may open. Only the admin (ADMIN_USER / ADMIN_PASS) gets here -
the server checks that before any of these run (auth.needs -> 'admin'), and each route checks again."""
import json
import re
from datetime import datetime

from .. import auth
from ..db import get_db, log, one, rows
from ..http import ApiError, route


def _admin(req):
    who = auth.current(req.cookie)
    if not who or not who.get("admin"):
        raise ApiError("Admin only", 403)
    return who


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _access(v):
    acc = [a for a in (v or []) if a in auth.PAGE_KEYS]
    if not acc:
        raise ApiError("Tick at least one page for this user")
    return acc


def _check_password(pw):
    if len(pw or "") < 6:
        raise ApiError("Password must have at least 6 characters")


@route("GET", r"/api/admin/users")
def list_users(req):
    _admin(req)
    out = rows("SELECT id, username, access, active, note, created_at, updated_at, last_login FROM users ORDER BY username")
    for r in out:
        r["access"] = json.loads(r["access"] or "[]")
    return dict(users=out, pages=[dict(key=k, name=n) for k, n in auth.PAGES], admin=auth.admin_user(),
                shared=bool(auth.shared_password()))


@route("POST", r"/api/admin/users")
def create_user(req):
    who = _admin(req)
    b = req.json
    name = str(b.get("username") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._@\-]{3,40}", name):
        raise ApiError("Username: 3-40 letters, digits or . _ - @ (no spaces)")
    if name.lower() == auth.admin_user().lower():
        raise ApiError("That is the admin's username")
    if one("SELECT id FROM users WHERE lower(username)=?", (name.lower(),)):
        raise ApiError("This username already exists")
    pw = str(b.get("password") or "")
    _check_password(pw)
    acc = _access(b.get("access"))
    con = get_db()
    con.execute("INSERT INTO users(username, pass_hash, access, active, version, note, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?)", (name, auth.hash_password(pw), json.dumps(acc), 1, 1,
                                           str(b.get("note") or "")[:200], _now(), _now()))
    con.commit()
    auth.forget(name)
    log("hub", "user created", f"{name}: {', '.join(acc)} (by {who['user']})")
    return dict(ok=True)


@route("PUT", r"/api/admin/users/(?P<id>\d+)")
def update_user(req):
    who = _admin(req)
    u = one("SELECT * FROM users WHERE id=?", (int(req.params["id"]),))
    if not u:
        raise ApiError("User not found", 404)
    b = req.json
    acc = _access(b.get("access")) if "access" in b else json.loads(u["access"] or "[]")
    active = (1 if b.get("active") else 0) if "active" in b else u["active"]
    note = str(b.get("note") if "note" in b else (u["note"] or ""))[:200]
    version = u["version"] or 1
    pw_hash = u["pass_hash"]
    if b.get("password"):
        _check_password(b["password"])
        pw_hash = auth.hash_password(b["password"])
        version += 1                        # logs the user out everywhere
    if active == 0 and u["active"]:
        version += 1
    con = get_db()
    con.execute("UPDATE users SET access=?, active=?, note=?, pass_hash=?, version=?, updated_at=? WHERE id=?",
                (json.dumps(acc), active, note, pw_hash, version, _now(), u["id"]))
    con.commit()
    auth.forget(u["username"])
    log("hub", "user changed", f"{u['username']}: {', '.join(acc)}{'' if active else ' (switched off)'}"
        f"{' + new password' if b.get('password') else ''} (by {who['user']})")
    return dict(ok=True)


@route("DELETE", r"/api/admin/users/(?P<id>\d+)")
def delete_user(req):
    who = _admin(req)
    u = one("SELECT username FROM users WHERE id=?", (int(req.params["id"]),))
    if not u:
        raise ApiError("User not found", 404)
    con = get_db()
    con.execute("DELETE FROM users WHERE id=?", (int(req.params["id"]),))
    con.commit()
    auth.forget(u["username"])
    log("hub", "user deleted", f"{u['username']} (by {who['user']})")
    return dict(ok=True)
