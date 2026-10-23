"""Logins and who may open what.

  ADMIN_USER / ADMIN_PASS (.env on the PC, Environment Variables on Vercel)
      the administrator: every page + the Admin page (create users, give each user pages)
  users (table `users`, made on the Admin page)
      username + password + the pages they may open (e.g. only CHEP and Supplementary Bill)
  APP_PASSWORD (the old shared password, still works): every page, no Admin page.
      Remove it from the env when everyone has their own login.
No ADMIN_PASS and no APP_PASSWORD -> no login at all (the PC app as before).

The login cookie is signed (HMAC) and names the user; the user's pages are read from the database on every
request (cached for a few seconds), so a change on the Admin page counts at once. Changing a user's password or
switching them off logs that user out; changing ADMIN_PASS / SESSION_SECRET logs everybody out.
Passwords are stored as PBKDF2-SHA256 hashes (200 000 rounds, own salt), never as text.
"""
import base64
import hashlib
import hmac
import json
import os
import time

from . import config

COOKIE = "sdew_hub_auth"
MAX_AGE = 30 * 24 * 3600  # stay logged in for 30 days
PUBLIC_PREFIXES = ("/login.html", "/api/login", "/api/logout", "/api/auth", "/css/", "/assets/")

# the pages a user can be given (key, name shown on the Admin page)
PAGES = [("today", "Today"), ("supp", "Supplementary Bill"), ("chep", "CHEP Transfer"), ("dqms", "DQMS Upload"),
         ("grin", "GRIN & Payments"), ("pay", "Payments"), ("find", "Find & trace"), ("drop", "Drop files"),
         ("items", "Follow-ups"), ("masters", "Masters")]
PAGE_KEYS = [k for k, _ in PAGES]
HUB_VIEWS = ("today", "find", "drop", "items", "masters")
ALL = "*"


# ------------------------------------------------------------------ settings from the env
def _env():
    return config.read_env()


def admin_user():
    return (_env().get("ADMIN_USER") or "admin").strip()


def admin_pass():
    return _env().get("ADMIN_PASS") or ""


def shared_password():
    return _env().get("APP_PASSWORD") or ""


def enabled():
    return bool(admin_pass() or shared_password())


def _secret():
    e = _env()
    base = e.get("SESSION_SECRET") or f"{admin_pass()}|{shared_password()}|sdew-hub"
    return hashlib.sha256(base.encode("utf-8")).digest()


# ------------------------------------------------------------------ passwords
def hash_password(pw, salt=None):
    salt = salt or os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, 200_000)
    return "pbkdf2$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def verify_password(pw, stored):
    try:
        _, s, h = stored.split("$")
        salt = base64.b64decode(s)
        return hmac.compare_digest(hash_password(pw, salt).split("$")[2], h)
    except (ValueError, AttributeError):
        return False


# ------------------------------------------------------------------ users
_cache = {}


def db_user(username):
    """Row of the users table (cached 10 s), or None."""
    key = (username or "").strip().lower()
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 10:
        return hit[1]
    try:
        from .db import one
        r = one("SELECT * FROM users WHERE lower(username)=?", (key,))
    except Exception:  # noqa: BLE001 - database not reachable: nobody but the admin gets in
        r = None
    _cache[key] = (time.time(), r)
    return r


def forget(username=None):
    if username is None:
        _cache.clear()
    else:
        _cache.pop((username or "").strip().lower(), None)


def _identity(name):
    """-> dict(user, admin, access [keys or '*'], v) for a cookie's user name, or None."""
    if name == "@admin":
        return dict(user=admin_user(), admin=True, access=ALL, v=hashlib.sha256(admin_pass().encode()).hexdigest()[:8])
    if name == "@shared":
        if not shared_password():
            return None
        return dict(user="shared login", admin=False, access=ALL,
                    v=hashlib.sha256(shared_password().encode()).hexdigest()[:8])
    r = db_user(name)
    if not r or not r.get("active"):
        return None
    access = [a for a in json.loads(r.get("access") or "[]") if a in PAGE_KEYS]
    return dict(user=r["username"], admin=False, access=access, v=str(r.get("version") or 1))


# ------------------------------------------------------------------ cookie
def _sign(payload):
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()[:40]
    return f"{raw}.{sig}"


def _unsign(value):
    try:
        raw, sig = value.rsplit(".", 1)
        if not hmac.compare_digest(sig, hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()[:40]):
            return None
        return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except (ValueError, TypeError):
        return None


def _cookie_value(cookie_header):
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
            return v
    return ""


def current(cookie_header):
    """The logged-in person: dict(user, admin, access) - or None. Everyone (admin) when no login is set."""
    if not enabled():
        return dict(user="", admin=True, access=ALL, open=True)
    p = _unsign(_cookie_value(cookie_header))
    if not p or p.get("exp", 0) < time.time():
        return None
    who = _identity(p.get("u", ""))
    if not who or str(who["v"]) != str(p.get("v")):
        return None
    return who


def authorised(cookie_header):
    return current(cookie_header) is not None


def login_cookie(name, secure=False):
    who = _identity(name)
    token = _sign(dict(u=name, v=who["v"], exp=int(time.time()) + MAX_AGE))
    s = "; Secure" if secure else ""
    return f"{COOKIE}={token}; Path=/; Max-Age={MAX_AGE}; HttpOnly; SameSite=Lax{s}"


def logout_cookie(secure=False):
    s = "; Secure" if secure else ""
    return f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax{s}"


def check_login(username, password):
    """-> the cookie name ('@admin', '@shared' or the username) or None."""
    username = (username or "").strip()
    ok = None
    if admin_pass() and username.lower() == admin_user().lower() and \
            hmac.compare_digest(password.encode(), admin_pass().encode()):
        ok = "@admin"
    elif not username and shared_password() and hmac.compare_digest(password.encode(), shared_password().encode()):
        ok = "@shared"
    elif username:
        r = db_user(username)
        if r and r.get("active") and verify_password(password, r.get("pass_hash") or ""):
            ok = r["username"]
            try:
                from .db import get_db
                con = get_db()
                con.execute("UPDATE users SET last_login=? WHERE id=?",
                            (time.strftime("%Y-%m-%dT%H:%M:%S"), r["id"]))
                con.commit()
            except Exception:  # noqa: BLE001
                pass
    if not ok:
        time.sleep(1)  # slow down guessing
    return ok


# ------------------------------------------------------------------ who may open what
def is_public(path):
    return any(path == p or path.startswith(p) for p in PUBLIC_PREFIXES)


def needs(path):
    """The page key a path belongs to: 'supp', 'today', ..., 'admin', 'hub-any' or None (no extra check)."""
    p = path.split("?")[0]
    if p.startswith("/api/admin") or p.startswith("/admin"):
        return "admin"
    if p.startswith("/api/supp/grin/"):
        return ("supp", "grin", "pay")       # Fetch GRIN is on these three pages
    for m in ("supp", "chep", "dqms", "grin", "pay"):
        if p.startswith(f"/api/{m}/") or p == f"/{m}" or p.startswith(f"/{m}/"):
            return m
    if p.startswith("/api/hub/"):
        rest = p[len("/api/hub/"):]
        if rest.startswith(("overview", "checks")):
            return "today"
        if rest.startswith("activity"):
            return ("today", "items")
        if rest.startswith(("search", "invoice", "part", "po", "dr")):
            return "find"
        if rest.startswith(("upload", "drop")):
            return "drop"
        if rest.startswith("open-items"):
            return ("items", "today")
        if rest.startswith("masters"):
            return "masters"
        return "today"
    if p in ("/", "/index.html"):
        return "hub-any"
    return None


def allowed(who, path):
    need = needs(path)
    if need is None or who is None:
        return need is None
    if need == "admin":
        return bool(who.get("admin"))
    if who["access"] == ALL:
        return True
    acc = set(who["access"])
    if need == "hub-any":                     # the home screen (app icons): everyone with at least one app
        return bool(acc)
    if isinstance(need, tuple):
        return bool(acc & set(need))
    return need in acc


def home_for(who):
    """Where to send someone who opened a page they may not see."""
    if not who or who["access"] == ALL or who["access"]:
        return "/"                            # the home screen shows only their apps
    for k in who["access"]:
        if k in ("supp", "chep", "dqms", "grin", "pay"):
            return f"/{k}/"
        if k in HUB_VIEWS:
            return f"/#{k}"
    return "/login.html?none=1"


def public_info(who):
    if not who:
        return None
    return dict(user=who["user"], admin=bool(who.get("admin")),
                access=PAGE_KEYS if who["access"] == ALL else who["access"], login=enabled())


def inject_user(html, who):
    """Pages get the logged-in person right away (window.HUB_USER): the header shows only their boxes."""
    info = public_info(who) or dict(user="", admin=not enabled(), access=PAGE_KEYS, login=enabled())
    tag = f"<script>window.HUB_USER={json.dumps(info)};</script>"
    # first thing in <head>: hubbar.js (also in <head>) reads it when it runs
    i = html.find("<head>")
    return html[:i + 6] + tag + html[i + 6:] if i >= 0 else tag + html
