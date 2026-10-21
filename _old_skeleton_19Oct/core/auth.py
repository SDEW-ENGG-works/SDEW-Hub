"""Password-only login, same idea as the CHEP / DQMS apps: cookie = HMAC of APP_PASSWORD."""
import hashlib
import hmac
from . import config

COOKIE = "sdewhub_auth"
MAX_AGE = 30 * 24 * 3600


def token():
    return hmac.new(config.APP_PASSWORD.encode(), b"sdewhub", hashlib.sha256).hexdigest()


def enabled():
    return bool(config.APP_PASSWORD)


def is_logged_in(cookie_header):
    if not enabled():
        return True
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE and hmac.compare_digest(v, token()):
            return True
    return False


def check_password(pw):
    return enabled() and hmac.compare_digest(pw or "", config.APP_PASSWORD)


def set_cookie():
    return f"{COOKIE}={token()}; Path=/; Max-Age={MAX_AGE}; HttpOnly; SameSite=Lax"


def clear_cookie():
    return f"{COOKIE}=; Path=/; Max-Age=0"
