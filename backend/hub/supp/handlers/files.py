import json
import urllib.parse

from ..db import rows
from ..http import ApiError, route
from ..services.ingest import ingest


@route("POST", r"/api/upload")
def upload(req):
    name = urllib.parse.unquote(req.arg("name", "upload"))
    data = req._body_bytes
    if not data:
        raise ApiError("Empty file.")
    return ingest(name, data)


@route("GET", r"/api/files")
def list_files(req):
    out = rows("SELECT id, kind, name, uploaded_at, rows, info FROM files ORDER BY id DESC LIMIT 300")
    for r in out:
        r["info"] = json.loads(r["info"] or "{}")
    return out
