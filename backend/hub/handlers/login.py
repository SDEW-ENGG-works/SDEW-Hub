from .. import auth, config
from ..http import ApiError, Response, route


@route("POST", r"/api/login")
def login(req):
    if not auth.enabled():
        return dict(ok=True, home="/")
    b = req.json
    from datetime import datetime
    from ..db import CURRENT_USER, log
    from ..services import safety
    user = str(b.get("username", ""))
    until = safety.locked_until(user)
    if until:
        raise ApiError(f"Too many wrong passwords - this login is locked until {datetime.fromtimestamp(until):%H:%M}. "
                       "Try again then, or ask the admin to unlock it.", 429)
    name = auth.check_login(user, str(b.get("password", "")))
    if not name:
        until = safety.login_failed(user)
        if until:
            raise ApiError(f"Too many wrong passwords - this login is locked for {safety.LOCK_MINUTES} minutes "
                           f"(until {datetime.fromtimestamp(until):%H:%M}).", 429)
        raise ApiError("Wrong username or password", 401)
    safety.login_ok(user)
    who = auth._identity(name)
    CURRENT_USER.set(who["user"])
    log("hub", "logged in", "")
    r = Response.json(dict(ok=True, home=auth.home_for(who)))
    r.headers["Set-Cookie"] = auth.login_cookie(name, secure=config.ON_VERCEL)
    return r


@route("POST", r"/api/logout")
def logout(req):
    r = Response.json(dict(ok=True))
    r.headers["Set-Cookie"] = auth.logout_cookie(secure=config.ON_VERCEL)
    return r


@route("GET", r"/api/auth")
def auth_status(req):
    who = auth.current(req.cookie)
    info = auth.public_info(who) or {}
    return dict(info, login=auth.enabled(), logged_in=bool(who), shared=bool(auth.shared_password()))
