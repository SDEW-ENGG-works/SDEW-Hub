"""Request/response objects and the URL router.

Both entry points (local server and Vercel) turn an incoming HTTP request
into a `Request`, call `dispatch()`, and write the returned `Response` back.
"""
import json
import re
import traceback
import urllib.parse


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


class Request:
    def __init__(self, method, raw_path, body_bytes=b""):
        parsed = urllib.parse.urlparse(raw_path)
        self.method = method.upper()
        self.path = parsed.path.rstrip("/") or "/"
        self.query = urllib.parse.parse_qs(parsed.query)
        self._body_bytes = body_bytes or b""
        self.params = {}

    def arg(self, name, default=""):
        return self.query.get(name, [default])[0]

    def flag(self, name):
        return self.arg(name, "false").lower() == "true"

    @property
    def json(self):
        if not self._body_bytes:
            return {}
        try:
            data = json.loads(self._body_bytes.decode("utf-8"))
        except ValueError:
            raise ApiError("Request body is not valid JSON.")
        if not isinstance(data, dict):
            raise ApiError("Request body must be a JSON object.")
        return data


class Response:
    def __init__(self, body=b"", status=200, content_type="application/json", headers=None):
        self.body = body
        self.status = status
        self.content_type = content_type
        self.headers = headers or {}

    @classmethod
    def json(cls, data, status=200):
        return cls(json.dumps(data, default=str).encode("utf-8"), status)

    @classmethod
    def error(cls, message, status=400):
        return cls.json({"error": message}, status)


# ---- routing table -------------------------------------------------------
_routes = []


def route(method, pattern):
    """Decorator: @route("GET", r"/api/processes/(?P<id>[\\w\\-]+)")"""
    regex = re.compile("^" + pattern + "$")

    def register(fn):
        _routes.append((method, regex, fn))
        return fn
    return register


def module_route(prefix):
    """route() for a module: '/api/bill/run' in the Supplementary Bill code becomes '/api/supp/bill/run'.
    The login routes stay shared by the whole hub."""
    def mroute(method, pattern):
        return route(method, pattern.replace("/api/", f"/api/{prefix}/", 1))
    return mroute


def dispatch(request):
    from .db import DatabaseUnavailable
    from . import handlers  # noqa: F401  (importing registers every route)

    path_matched = False
    for method, regex, fn in _routes:
        m = regex.match(request.path)
        if not m:
            continue
        path_matched = True
        if method != request.method:
            continue
        request.params = m.groupdict()
        try:
            result = fn(request)
        except ApiError as e:
            return Response.error(e.message, e.status)
        except DatabaseUnavailable as e:
            print(f"Database unavailable: {e}")
            return Response.error("The database is not reachable right now. Please try again in a moment.", 503)
        except Exception as e:  # never leak a stack trace to the browser
            traceback.print_exc()
            return Response.error(f"Server error: {e}", 500)
        if isinstance(result, Response):
            return result
        if isinstance(result, tuple):
            return Response.json(result[0], result[1])
        return Response.json(result)
    if path_matched:
        return Response.error("Method not allowed", 405)
    return Response.error("Endpoint not found", 404)
