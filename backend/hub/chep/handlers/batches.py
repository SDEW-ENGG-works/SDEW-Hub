import urllib.parse

from ..db import get_setting, rows, set_setting
from ..http import ApiError, route
from ..services import store
from ..services.builder import part_master
from ..services.defaults import load_settings


@route("POST", r"/api/upload")
def upload(req):
    name = urllib.parse.unquote(req.arg("name", "upload"))
    data = req._body_bytes
    if not data:
        raise ApiError("Empty file.")
    return store.ingest(name, data)


@route("GET", r"/api/batches")
def list_batches(req):
    return rows("SELECT b.id, b.name, b.uploaded_at, COUNT(r.id) runs FROM batches b "
                "LEFT JOIN chep_runs r ON r.batch_id=b.id GROUP BY b.id ORDER BY b.id DESC LIMIT 100")


@route("GET", r"/api/batches/(?P<id>\d+)")
def get_batch(req):
    b = store.get_batch(int(req.params["id"]))
    sheets = []
    for s in b["parsed"]["sheets"]:
        d = {k: s[k] for k in ("name", "title", "plant", "date", "selected", "size_columns", "unknown_sizes")}
        d.update(lines=len(s["lines"]), cheps=sum(ln["chep"] for ln in s["lines"]))
        sheets.append(d)
    return dict(id=b["id"], name=b["name"], uploaded_at=b["uploaded_at"], sheets=sheets,
                skipped=b["parsed"]["skipped"], latest=b["parsed"]["latest"])


@route("POST", r"/api/batches/(?P<id>\d+)/reread")
def reread(req):
    store.reparse(int(req.params["id"]))
    return get_batch(req)


@route("POST", r"/api/batches/(?P<id>\d+)/preview")
def preview(req):
    return store.preview(int(req.params["id"]), req.json)


@route("POST", r"/api/batches/(?P<id>\d+)/generate")
def generate(req):
    r = store.generate(int(req.params["id"]), req.json)
    from ...db import log
    log("chep", "CHEP file saved", f"{r['file_name']}: {r['summary'].get('invoices')} invoices, {r['summary'].get('rows')} rows")
    return r


@route("POST", r"/api/batches/clear")
def clear_page(req):
    """Refresh on the Create page: the page goes back to empty. Nothing is deleted - the packing
    lists stay in the database (History needs them); they are just not opened again."""
    last = rows("SELECT id FROM batches ORDER BY id DESC LIMIT 1")
    set_setting("create_cleared", last[0]["id"] if last else 0)
    return dict(ok=True)


@route("GET", r"/api/bootstrap")
def bootstrap(req):
    last = rows("SELECT id FROM batches ORDER BY id DESC LIMIT 1")
    if last and last[0]["id"] <= int(get_setting("create_cleared", 0) or 0):
        last = []  # page was cleared with Refresh - open empty until a new packing list comes
    from .. import config
    return dict(settings=load_settings(), template=store.template_summary(), db_mode=config.db_mode(),
                last_batch=last[0]["id"] if last else None,
                counts=dict(parts=len(part_master()),
                            runs=rows("SELECT COUNT(*) n FROM chep_runs")[0]["n"]))
