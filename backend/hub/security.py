"""Browser protections and limits, added to every answer by local_server.py (PC) and wsgi.py (website).

  Content-Security-Policy   the pages may load scripts / styles / pictures only from this site (+ Google Fonts),
                            talk only to this site and to the Tally Bridge on the same computer (localhost:9001),
                            and may not be shown inside another site's frame
  X-Frame-Options           the same 'no frames' for older browsers (stops click-jacking)
  X-Content-Type-Options    a file is used only as what it says it is
  Referrer-Policy           other sites are not told which hub page a link was clicked on
  Permissions-Policy        no camera, microphone, location, payment
  Strict-Transport-Security the website is always opened with https (website only)
  Same-origin check         a change (POST / PUT / DELETE) sent by another website is refused
  Upload limit              MAX_UPLOAD_MB in .env (default 50 MB per request)
"""
import urllib.parse

from . import config

CSP = ("default-src 'self'; "
       "script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com data:; "
       "img-src 'self' data: blob:; "
       "connect-src 'self' http://localhost:9001 http://127.0.0.1:9001; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'")


def headers():
    h = [("Content-Security-Policy", CSP), ("X-Frame-Options", "DENY"), ("X-Content-Type-Options", "nosniff"),
         ("Referrer-Policy", "same-origin"),
         ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")]
    if config.ON_VERCEL:
        h.append(("Strict-Transport-Security", "max-age=31536000; includeSubDomains"))
    return h


def max_body():
    try:
        mb = float(config.read_env().get("MAX_UPLOAD_MB") or 50)
    except ValueError:
        mb = 50
    return int(mb * 1024 * 1024)


def too_big(length):
    try:
        return int(length or 0) > max_body()
    except ValueError:
        return True


def same_origin(method, origin, referer, host):
    """False when a change comes from a page of another website (CSRF). Requests without Origin/Referer
    (tools, curl, the PC agent) are allowed - the login cookie is SameSite=Lax anyway."""
    if method in ("GET", "HEAD", "OPTIONS"):
        return True
    src = origin or referer
    if not src or src == "null":
        return True
    try:
        h = urllib.parse.urlparse(src).netloc.lower()
    except ValueError:
        return False
    return h == (host or "").lower()


TOO_BIG = b'{"error": "File too large for the hub (limit MAX_UPLOAD_MB in .env)."}'
CROSS_SITE = b'{"error": "Refused: this change was sent from another website."}'
