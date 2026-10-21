"""Local server: serves the hub page, the three module pages and every /api route on one port."""
import http.server
import os
import sys

from . import auth, config
from .assets import index_page, stamp_index_files
from .db import get_db
from .http import Request, dispatch

LONG_CACHE = "public, max-age=31536000, immutable"
NO_CACHE = "no-store, no-cache, must-revalidate, max-age=0"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=config.FRONTEND_DIR, **kwargs)

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or "") or (args and str(args[1])[:1] in "45"):
            super().log_message(fmt, *args)

    def end_headers(self):
        if self.path.startswith("/api/"):
            self.send_header("Cache-Control", NO_CACHE)
        elif ("/css/" in self.path or "/js/" in self.path or "/assets/" in self.path) and "v=" in self.path:
            self.send_header("Cache-Control", LONG_CACHE)
        else:
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _api(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        resp = dispatch(Request(self.command, self.path, body))
        if config.db_mode() == "cloud":
            try:  # Turso: send any writes still queued
                from .db import commit_all
                commit_all()
            except Exception:  # noqa: BLE001
                pass
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(resp.body)))
        for k, v in resp.headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(resp.body)

    def _blocked(self):
        """True (and answered) when a password is set and this browser has not logged in."""
        path = self.path.split("?")[0]
        if auth.is_public(path) or auth.authorised(self.headers.get("Cookie")):
            return False
        if path.startswith("/api/"):
            body = b'{"error": "Please log in", "login": true}'
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(302)
            self.send_header("Location", "/login.html")
            self.send_header("Content-Length", "0")
            self.end_headers()
        return True

    def do_GET(self):
        if self._blocked():
            return
        if self.path.startswith("/api/"):
            return self._api()
        p = self.path.split("?")[0]
        if p in ("/supp", "/chep", "/dqms", "/grin"):
            self.send_response(301)
            self.send_header("Location", p + "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        page = index_page(self.path)
        if page:
            body = page[0].encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def do_POST(self):
        return None if self._blocked() else self._api()

    def do_PUT(self):
        return None if self._blocked() else self._api()

    def do_DELETE(self):
        return None if self._blocked() else self._api()


def first_import():
    """First start on this PC: the hub has never been filled -> copy all data of the three old apps
    (Supplementary Bill from this PC, CHEP / DQMS from their Turso databases) and check it."""
    if config.db_mode() != "local":
        return
    try:
        con = get_db()
        if con.execute("SELECT 1 FROM settings WHERE key='hub.import'").fetchone():
            return
    except Exception:  # noqa: BLE001
        return
    tools = os.path.join(config.PROJECT_ROOT, "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    print("=" * 78 + "\nFirst start: copying all data from SupplementaryBill, CHEPTransfer and DQMSUpload ...\n" + "=" * 78)
    try:
        import import_from_apps
        import verify_hub
        import_from_apps.main(["--yes"])
        print()
        verify_hub.main([], exit_code=False)
        print("=" * 78)
    except SystemExit as e:
        print(f"Import stopped: {e}\nStart again after fixing it, or run import_data.bat.")
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"Import failed: {e} - the hub starts anyway; run import_data.bat to try again.")


def run_server(port=None):
    if port is None:
        env_port = config.read_env().get("HUB_PORT")
        port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else int(
            os.environ.get("PORT") or env_port or config.DEFAULT_PORT)
    try:
        stamp_index_files()
    except OSError:
        pass
    first_import()
    get_db()
    try:  # CHEP: jobs sent from the website reach this PC through the shared cloud database
        from .chep.services.leap_remote import start_agent
        start_agent()
    except Exception as e:  # noqa: BLE001
        print("[LEAP agent] not started:", e)
    server = http.server.ThreadingHTTPServer(("", port), Handler)
    print(f"SDEW Hub running on http://localhost:{port}   ({config.db_mode()} database)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.server_close()
