"""Password-only login (APP_PASSWORD in Vercel env vars, or in .env on the PC).

No password set -> the app is open, as before. With a password, every page and /api
call needs the login cookie; /login.html asks for the password and sets it.
The cookie is an HMAC of the password, so changing APP_PASSWORD logs everybody out.
"""
import hashlib
import hmac
import time

from . import config

COOKIE = "sdew_hub_auth"
MAX_AGE = 30 * 24 * 3600  # stay logged in for 30 days
PUBLIC_PREFIXES = ("/login.html", "/api/login", "/api/logout", "/api/auth", "/css/", "/assets/")


def password():
    return config.read_env().get("APP_PASSWORD") or ""


def enabled():
    return bool(password())


def token():
    return hmac.new(password().encode("utf-8"), b"sdew-hub-login", hashlib.sha256).hexdigest()


def _cookie_value(cookie_header):
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
            return v
    return ""


def is_public(path):
    return any(path == p or path.startswith(p) for p in PUBLIC_PREFIXES)


def authorised(cookie_header):
    if not enabled():
        return True
    return hmac.compare_digest(_cookie_value(cookie_header), token())


def check_password(given):
    ok = enabled() and hmac.compare_digest((given or "").encode("utf-8"), password().encode("utf-8"))
    if not ok:
        time.sleep(1)  # slow down guessing
    return ok


def login_cookie(secure=False):
    s = "; Secure" if secure else ""
    return f"{COOKIE}={token()}; Path=/; Max-Age={MAX_AGE}; HttpOnly; SameSite=Lax{s}"


def logout_cookie(secure=False):
    s = "; Secure" if secure else ""
    return f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax{s}"
