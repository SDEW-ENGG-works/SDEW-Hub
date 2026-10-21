"""SDEW Hub - one app for POs, DRs, invoices, CHEP, DQMS, GRIN and the supplementary bill.

Start: python server.py   then open http://localhost:8050
Standard library only (openpyxl / xlrd / pypdf are optional, for file recognition).
"""
import datetime
import json
import mimetypes
import re
import sqlite3
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

from core import auth, config, db, exceptions, legacy, recognize

# Tables the Masters / data pages may read and edit, with their key column.
EDITABLE = {
    "plants": "code", "parts": "part_no", "part_corrections": "id", "crate_sizes": "size",
    "fixed_rates": "id", "reason_codes": "code", "settings": "key", "pos": "po_no",
}
READABLE = set(EDITABLE) | {"po_lines", "po_prices", "drs", "invoices", "invoice_lines",
                            "chep_transfers", "dqms_uploads", "grin", "inbox", "open_items", "audit_log"}

ROUTES = []


def route(method, pattern):
    def wrap(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return wrap


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def log(action, detail=""):
    db.execute("INSERT INTO audit_log(at,action,detail) VALUES (?,?,?)", (now(), action, detail))


def columns(table):
    return [r["name"] for r in db.rows(f"PRAGMA table_info({table})")]


# ---------------------------------------------------------------- API ---------------

@route("GET", "/api/status")
def api_status(h, q):
    counts = {t: db.rows(f"SELECT COUNT(*) n FROM {t}")[0]["n"]
              for t in ["pos", "drs", "invoices", "chep_transfers", "dqms_uploads", "grin",
                        "parts", "inbox"]}
    open_items = db.rows("SELECT COUNT(*) n FROM open_items WHERE status='open'")[0]["n"]
    exc = sum(r["count"] for r in exceptions.run())
    return {"counts": counts, "open_items": open_items, "exceptions": exc,
            "legacy": legacy.status(), "login": auth.enabled()}


@route("GET", "/api/table/(?P<table>[a-z_]+)")
def api_table(h, q, table):
    if table not in READABLE:
        return 404, {"error": "Unknown table"}
    limit = min(int(q.get("limit", ["500"])[0]), 5000)
    offset = int(q.get("offset", ["0"])[0])
    search = q.get("q", [""])[0].strip()
    cols = columns(table)
    where, args = "", []
    if search:
        where = " WHERE " + " OR ".join(f"CAST({c} AS TEXT) LIKE ?" for c in cols)
        args = [f"%{search}%"] * len(cols)
    total = db.rows(f"SELECT COUNT(*) n FROM {table}{where}", args)[0]["n"]
    data = db.rows(f"SELECT * FROM {table}{where} LIMIT ? OFFSET ?", args + [limit, offset])
    return {"table": table, "columns": cols, "rows": data, "total": total,
            "key": EDITABLE.get(table), "editable": table in EDITABLE}


@route("POST", "/api/table/(?P<table>[a-z_]+)")
def api_table_save(h, q, table):
    """Insert or update one row. Body: {"row": {...}, "original_key": value-or-null}."""
    if table not in EDITABLE:
        return 403, {"error": "This table is filled by the modules, not edited by hand."}
    body = h.json_body()
    row = {k: (v if v != "" else None) for k, v in body.get("row", {}).items() if k in columns(table)}
    key = EDITABLE[table]
    orig = body.get("original_key")
    if orig not in (None, ""):
        sets = ", ".join(f"{c}=?" for c in row)
        db.execute(f"UPDATE {table} SET {sets} WHERE {key}=?", list(row.values()) + [orig])
        log("edit", f"{table} {orig}")
    else:
        if key == "id":
            row.pop("id", None)
        if not row:
            return 400, {"error": "Nothing to save."}
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        try:
            db.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values()))
        except sqlite3.IntegrityError as e:
            return 400, {"error": f"Could not add: {e}"}
        log("add", f"{table} {row.get(key, '')}")
    return {"ok": True}


@route("POST", "/api/table/(?P<table>[a-z_]+)/delete")
def api_table_delete(h, q, table):
    if table not in EDITABLE:
        return 403, {"error": "Not editable"}
    key = h.json_body().get("key")
    db.execute(f"DELETE FROM {table} WHERE {EDITABLE[table]}=?", (key,))
    log("delete", f"{table} {key}")
    return {"ok": True}


@route("GET", "/api/exceptions")
def api_exceptions(h, q):
    return {"rules": exceptions.run()}


@route("GET", "/api/open-items")
def api_open_items(h, q):
    return {"items": db.rows("SELECT * FROM open_items ORDER BY status DESC, module, id")}


@route("POST", "/api/open-items")
def api_open_items_save(h, q):
    b = h.json_body()
    if b.get("id"):
        status = b.get("status", "open")
        db.execute("UPDATE open_items SET status=?, done_at=? WHERE id=?",
                   (status, now() if status == "done" else None, b["id"]))
    else:
        db.execute("INSERT INTO open_items(module,title,detail,created_at) VALUES (?,?,?,?)",
                   (b.get("module", "hub"), b.get("title", "").strip(), b.get("detail", ""), now()))
    return {"ok": True}


@route("POST", "/api/inbox")
def api_inbox_upload(h, q):
    name = urllib.parse.unquote(h.headers.get("X-Filename", "upload.bin"))
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    data = h.read_body()
    kind = recognize.recognise(name, data)
    info = recognize.describe(kind)
    folder = config.DATA / "inbox" / datetime.date.today().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    n = 1
    while path.exists():
        path = folder / f"{path.stem.split('__')[0]}__{n}{path.suffix}"
        n += 1
    path.write_bytes(data)
    db.execute("INSERT INTO inbox(filename,kind,module,size,path,received_at) VALUES (?,?,?,?,?,?)",
               (name, kind, info["module"], len(data), str(path.relative_to(config.ROOT)), now()))
    log("inbox", f"{name} -> {kind}")
    return {"ok": True, **info, "filename": name}


@route("POST", "/api/inbox/(?P<item_id>\\d+)/status")
def api_inbox_status(h, q, item_id):
    db.execute("UPDATE inbox SET status=? WHERE id=?", (h.json_body().get("status", "done"), item_id))
    return {"ok": True}


@route("GET", "/api/legacy")
def api_legacy(h, q):
    return {"apps": legacy.status()}


@route("POST", "/api/legacy/(?P<key>[a-z]+)/(?P<action>start|stop)")
def api_legacy_action(h, q, key, action):
    if key not in config.LEGACY_BY_KEY:
        return 404, {"error": "Unknown app"}
    ok, msg = (legacy.start if action == "start" else legacy.stop)(key)
    return {"ok": ok, "message": msg}


@route("GET", "/api/legacy/(?P<key>[a-z]+)/tables")
def api_legacy_tables(h, q, key):
    app = config.LEGACY_BY_KEY.get(key)
    if not app:
        return 404, {"error": "Unknown app"}
    out = []
    for path in db.legacy_db_paths(app):
        con = db.legacy_connect(path)
        try:
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                 "AND name NOT LIKE 'sqlite_%' ORDER BY name"):
                n = con.execute(f'SELECT COUNT(*) FROM "{r["name"]}"').fetchone()[0]
                out.append({"db": path.name, "table": r["name"], "rows": n})
        finally:
            con.close()
    return {"tables": out}


@route("GET", "/api/legacy/(?P<key>[a-z]+)/table/(?P<table>[A-Za-z0-9_]+)")
def api_legacy_table(h, q, key, table):
    app = config.LEGACY_BY_KEY.get(key)
    for path in db.legacy_db_paths(app or {"folder": "", "dbs": []}):
        con = db.legacy_connect(path)
        try:
            exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                 (table,)).fetchone()
            if not exists:
                continue
            limit = min(int(q.get("limit", ["200"])[0]), 2000)
            offset = int(q.get("offset", ["0"])[0])
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
            total = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            data = [dict(r) for r in con.execute(f'SELECT * FROM "{table}" LIMIT ? OFFSET ?',
                                                 (limit, offset))]
            return {"table": table, "columns": cols, "rows": data, "total": total}
        finally:
            con.close()
    return 404, {"error": "Table not found"}


@route("POST", "/api/login")
def api_login(h, q):
    if auth.check_password(h.json_body().get("password")):
        return 200, {"ok": True}, {"Set-Cookie": auth.set_cookie()}
    return 401, {"error": "Wrong password."}


@route("POST", "/api/logout")
def api_logout(h, q):
    return 200, {"ok": True}, {"Set-Cookie": auth.clear_cookie()}


# ---------------------------------------------------------------- server -------------

class Handler(BaseHTTPRequestHandler):
    server_version = "SDEWHub/1.0"

    def log_message(self, fmt, *args):
        pass

    def read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def json_body(self):
        try:
            return json.loads(self.read_body() or b"{}")
        except json.JSONDecodeError:
            return {}

    def send(self, code, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def handle_api(self, method):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        open_paths = {"/api/login"}
        if url.path not in open_paths and not auth.is_logged_in(self.headers.get("Cookie")):
            return self.send(401, {"error": "login"})
        for m, rx, fn in ROUTES:
            match = rx.match(url.path)
            if m == method and match:
                try:
                    res = fn(self, q, **match.groupdict())
                except Exception as e:
                    return self.send(500, {"error": str(e)})
                if isinstance(res, tuple):
                    return self.send(res[0], res[1], extra=res[2] if len(res) > 2 else None)
                return self.send(200, res)
        return self.send(404, {"error": "Not found"})

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/"):
            return self.handle_api("GET")
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        f = (config.STATIC / rel).resolve()
        if not str(f).startswith(str(config.STATIC.resolve())) or not f.is_file():
            f = config.STATIC / "index.html"
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        self.send(200, f.read_bytes(), ctype)

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self.handle_api("POST")
        self.send(404, {"error": "Not found"})


def main():
    db.init()
    srv = ThreadingHTTPServer(("127.0.0.1", config.PORT), Handler)
    print(f"SDEW Hub running at http://localhost:{config.PORT}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        legacy.stop_all()


if __name__ == "__main__":
    main()
