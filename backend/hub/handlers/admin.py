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


# ------------------------------------------------------------------ safety: backups, cleared data, locked logins
def _module_con(module):
    if module == "chep":
        from ..chep.db import get_db as g
        return g()
    if module == "dqms":
        from ..dqms.db import get_db as g
        return g()
    return get_db()


def _remote():
    """The website cannot write files: backups / restores there are jobs for the SDEW PC."""
    from .. import config
    return config.ON_VERCEL


@route("GET", r"/api/admin/safety")
def safety_info(req):
    _admin(req)
    from ..services import backup, pc_jobs, safety
    return dict(backups=backup.listing(), backup=backup.info(), remote=_remote() and not _website_blob(),
                website=_remote(),
                agent=pc_jobs.agent_info() if _remote() else None,
                job=_job_status(), wipes=safety.snapshots(), locked=safety.locked_list())


def _job_status():
    from ..services import backup, pc_jobs
    if not _remote() or _website_blob():
        return dict(backup.STATUS)
    a, b = pc_jobs.latest("backup"), pc_jobs.latest("restore")
    kind = "restore" if b and (not a or b["id"] > a["id"]) else "backup"
    return pc_jobs.status(kind)


def _website_blob():
    """The website with a Vercel Blob store: backups / restores are done right here, no PC needed."""
    from ..services import blobstore
    return _remote() and blobstore.enabled()


@route("POST", r"/api/admin/backup")
def backup_now(req):
    who = _admin(req)
    from ..services import backup, pc_jobs
    if _website_blob():
        try:
            return backup.run_now("backup", dict(reason="manual"), user=who["user"])
        except RuntimeError as e:
            raise ApiError(str(e))
    if _remote():
        try:
            return pc_jobs.queue("backup", dict(reason="manual", user=who["user"]))
        except RuntimeError as e:
            raise ApiError(str(e))
    if not backup.start("backup", dict(reason="manual"), user=who["user"]):
        raise ApiError("A backup or restore is already running - wait for it to finish")
    return dict(backup.STATUS)


@route("POST", r"/api/admin/restore")
def restore_backup(req):
    who = _admin(req)
    b = req.json
    name = str(b.get("name") or "")
    if str(b.get("confirm") or "").strip().upper() != "RESTORE":
        raise ApiError('Type RESTORE to confirm')
    if not one("SELECT id FROM backups WHERE name=?", (name,)):
        raise ApiError("Backup not found")
    from ..services import backup, pc_jobs
    if _website_blob():
        try:
            return backup.run_now("restore", dict(name=name), user=who["user"])
        except RuntimeError as e:
            raise ApiError(str(e))
    if _remote():
        try:
            return pc_jobs.queue("restore", dict(name=name, user=who["user"]))
        except RuntimeError as e:
            raise ApiError(str(e))
    if not backup.start("restore", dict(name=name), user=who["user"]):
        raise ApiError("A backup or restore is already running - wait for it to finish")
    return dict(backup.STATUS)


@route("GET", r"/api/admin/backup/status")
def backup_status(req):
    _admin(req)
    return _job_status()


@route("GET", r"/api/admin/backup/file")
def backup_file(req):
    _admin(req)
    from ..http import Response
    from ..services import backup
    if _remote():
        raise ApiError("Backup files are on the SDEW PC (data\\backups) - download them from the hub there")
    p = backup._find(req.arg("name"))
    if not p:
        raise ApiError("File not found on this PC", 404)
    with open(p, "rb") as fh:
        data = fh.read()
    import os as _os
    return Response(data, content_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{_os.path.basename(p)}"'})


@route("POST", r"/api/admin/wipes/(?P<id>\d+)/restore")
def wipe_restore(req):
    _admin(req)
    from ..services import safety
    try:
        n = safety.restore_snapshot(int(req.params["id"]), _module_con)
    except ValueError as e:
        raise ApiError(str(e), 404)
    return dict(ok=True, rows=n)


@route("POST", r"/api/admin/unlock")
def unlock_login(req):
    _admin(req)
    from ..services import safety
    name = str(req.json.get("username") or "")
    if not name:
        raise ApiError("Which login?")
    safety.unlock(name)
    return dict(ok=True)


# ------------------------------------------------------------------ Vercel Cron: nightly backup of the website
@route("GET", r"/api/cron/backup")
def cron_backup(req):
    """Called by Vercel Cron (vercel.json "crons"). With CRON_SECRET set, Vercel sends it as
    'Authorization: Bearer <CRON_SECRET>' and nothing else may run this. Without it, only one backup per
    20 hours can be started this way (so the open link cannot be misused to fill the store)."""
    import hmac
    import os
    from datetime import datetime, timedelta
    from .. import config
    from ..services import backup, blobstore
    secret = os.environ.get("CRON_SECRET") or config.read_env().get("CRON_SECRET") or ""
    auth_h = (req.headers or {}).get("authorization", "")
    if secret:
        if not hmac.compare_digest(auth_h, f"Bearer {secret}"):
            raise ApiError("Not allowed", 401)
    else:
        last = one("SELECT at FROM backups WHERE reason='nightly' ORDER BY at DESC LIMIT 1")
        if last and last["at"] > (datetime.now() - timedelta(hours=20)).isoformat(timespec="seconds"):
            return dict(ok=True, skipped=f"a nightly backup was made at {last['at']}")
    if not blobstore.enabled():
        raise ApiError("No Blob store connected: " + blobstore.why_not(), 503)
    st = backup.run_now("backup", dict(reason="nightly"), user="nightly (website)")
    if st.get("error"):
        raise ApiError(st["error"], 500)
    try:
        from ..db import set_setting
        set_setting("hub.last_cloud_backup", datetime.now().isoformat(timespec="seconds"))
    except Exception:  # noqa: BLE001
        pass
    return dict(ok=True, result=st.get("result"))
