"""WSGI app for Vercel (also runs anywhere WSGI runs). Same pages and /api routes as local_server.py."""
import mimetypes
import os

from . import auth, config, security
from .assets import index_page
from .http import Request, dispatch

LONG_CACHE = "public, max-age=31536000, immutable"
NO_CACHE = "no-store, no-cache, must-revalidate, max-age=0"


def _static(path):
    rel = path.lstrip("/")
    full = os.path.normpath(os.path.join(config.FRONTEND_DIR, rel))
    if not full.startswith(os.path.normpath(config.FRONTEND_DIR) + os.sep) or not os.path.isfile(full):
        return None
    with open(full, "rb") as fh:
        body = fh.read()
    ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/javascript",):
        ctype += "; charset=utf-8"
    return body, ctype


def app(environ, start_response):
    """Every answer gets the browser protections of security.py."""
    def sr(status, headers, exc_info=None):
        return start_response(status, list(headers) + security.headers(), exc_info) if exc_info else \
            start_response(status, list(headers) + security.headers())
    return _app(environ, sr)


def _app(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "/") or "/"
    query = environ.get("QUERY_STRING", "")

    who = None
    if not auth.is_public(path):
        who = auth.current(environ.get("HTTP_COOKIE"))
        if not who or not auth.allowed(who, path):
            if path.startswith("/api/"):
                body = (b'{"error": "Please log in", "login": true}' if not who else
                        b'{"error": "Your login does not include this page - ask the admin", "forbidden": true}')
                start_response("401 Unauthorized" if not who else "403 Forbidden",
                               [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
                return [body]
            start_response("302 Found", [("Location", "/login.html" if not who else auth.home_for(who)),
                                         ("Content-Length", "0")])
            return [b""]

    if path.startswith("/api/"):
        if security.too_big(environ.get("CONTENT_LENGTH")):
            start_response("413 Too Large", [("Content-Type", "application/json"),
                                             ("Content-Length", str(len(security.TOO_BIG)))])
            return [security.TOO_BIG]
        if not security.same_origin(environ.get("REQUEST_METHOD", "GET"), environ.get("HTTP_ORIGIN"),
                                    environ.get("HTTP_REFERER"), environ.get("HTTP_X_FORWARDED_HOST") or environ.get("HTTP_HOST")):
            start_response("403 Forbidden", [("Content-Type", "application/json"),
                                             ("Content-Length", str(len(security.CROSS_SITE)))])
            return [security.CROSS_SITE]
        oidc = environ.get("HTTP_X_VERCEL_OIDC_TOKEN")
        if oidc:  # lets this request start a Vercel Sandbox (cloud browser for LEAP) without a token
            os.environ["VERCEL_OIDC_TOKEN"] = oidc
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        body = environ["wsgi.input"].read(length) if length else b""
        req = Request(method, path + ("?" + query if query else ""), body)
        req.cookie = environ.get("HTTP_COOKIE") or ""
        resp = dispatch(req)
        try:  # Turso: send any writes still queued
            from .db import commit_all
            commit_all()
        except Exception:  # noqa: BLE001
            pass
        headers = [("Content-Type", resp.content_type), ("Content-Length", str(len(resp.body))),
                   ("Cache-Control", NO_CACHE)] + list(resp.headers.items())
        start_response(f"{resp.status} {'OK' if resp.status < 400 else 'Error'}", headers)
        return [resp.body]

    if path in ("/supp", "/chep", "/dqms", "/grin", "/pay", "/admin"):
        start_response("301 Moved", [("Location", path + "/"), ("Content-Length", "0")])
        return [b""]
    page = index_page(path)
    if page:
        html = auth.inject_user(page[0], who).encode("utf-8")
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(html))),
                                  ("Cache-Control", "no-cache")])
        return [html]

    found = _static(path)
    if not found:
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"Not found"]
    body, ctype = found
    cache = LONG_CACHE if "v=" in query else "no-cache"
    start_response("200 OK", [("Content-Type", ctype), ("Content-Length", str(len(body))), ("Cache-Control", cache)])
    return [body]
