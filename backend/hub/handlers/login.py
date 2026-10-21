from .. import auth, config
from ..http import ApiError, Response, route


@route("POST", r"/api/login")
def login(req):
    if not auth.enabled():
        return dict(ok=True)
    if not auth.check_password(str(req.json.get("password", ""))):
        raise ApiError("Wrong password", 401)
    r = Response.json(dict(ok=True))
    r.headers["Set-Cookie"] = auth.login_cookie(secure=config.ON_VERCEL)
    return r


@route("POST", r"/api/logout")
def logout(req):
    r = Response.json(dict(ok=True))
    r.headers["Set-Cookie"] = auth.logout_cookie(secure=config.ON_VERCEL)
    return r


@route("GET", r"/api/auth")
def auth_status(req):
    return dict(login=auth.enabled())
