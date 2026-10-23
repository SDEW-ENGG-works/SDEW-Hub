from .. import auth, config
from ..http import ApiError, Response, route


@route("POST", r"/api/login")
def login(req):
    if not auth.enabled():
        return dict(ok=True, home="/")
    b = req.json
    name = auth.check_login(str(b.get("username", "")), str(b.get("password", "")))
    if not name:
        raise ApiError("Wrong username or password", 401)
    who = auth._identity(name)
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
