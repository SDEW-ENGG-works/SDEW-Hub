"""Tally bridge: lets the SDEW Hub WEBSITE read the Tally of the computer you are using.

A web page cannot talk to Tally (localhost:9000) by itself: Tally does not send the permission headers a
browser needs. This tiny program runs on each computer that has Tally and passes the website's requests on:

    browser on this PC  ->  http://localhost:9001 (this bridge)  ->  Tally http://localhost:9000

So "Pull from Tally" on the website always reads THIS computer's Tally - whichever computer you open the site on.
Only the hub's own pages may use it (allowed origins below). Nothing to install - Python only.

    python tools\\tally_bridge.py                     run (keep the window open)
    python tools\\tally_bridge.py --startup           also start it automatically when Windows starts
    python tools\\tally_bridge.py --tally http://localhost:9000 --port 9001
"""
import http.server
import json
import os
import socket
import sys
import urllib.request

PORT = 9001
TALLY = "http://localhost:9000"
ORIGINS = {"https://sdew-hub.vercel.app", "http://localhost:8050", "http://127.0.0.1:8050"}
COMPANIES = """<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE>
<ID>SDEWHubCompanies</ID></HEADER><BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
</STATICVARIABLES><TDL><TDLMESSAGE><COLLECTION NAME="SDEWHubCompanies" ISMODIFY="No"><TYPE>Company</TYPE>
<FETCH>Name</FETCH></COLLECTION></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"""


def tally_post(xml, timeout=180):
    req = urllib.request.Request(TALLY, data=xml if isinstance(xml, bytes) else xml.encode("utf-8"),
                                 headers={"Content-Type": "text/xml; charset=utf-8"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        raw = r.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    if len(raw) > 3 and raw[1:2] == b"\x00":
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("utf-8", errors="replace")


class Bridge(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if "/tally" in self.path:
            sys.stdout.write(f"  {self.address_string()} {fmt % args}\n")

    def _cors(self):
        origin = self.headers.get("Origin") or ""
        if origin in ORIGINS or origin.endswith(".vercel.app") and "sdew-hub" in origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")   # Chrome: public site -> this PC
        self.send_header("Access-Control-Max-Age", "600")

    def _allowed(self):
        o = self.headers.get("Origin") or ""
        return not o or o in ORIGINS or (o.endswith(".vercel.app") and "sdew-hub" in o)

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self._allowed():
            return self._send(403, json.dumps(dict(error="This page may not use the Tally bridge")))
        if self.path.startswith("/ping"):
            out = dict(ok=True, bridge=True, host=socket.gethostname(), tally=TALLY)
            try:
                import re
                text = tally_post(COMPANIES, timeout=10)
                out.update(tally_ok=True, companies=re.findall(r'<COMPANY NAME="([^"]+)"', text))
            except Exception as e:  # noqa: BLE001
                out.update(tally_ok=False, error=f"Tally is not answering on {TALLY}: {e}")
            return self._send(200, json.dumps(out))
        self._send(404, json.dumps(dict(error="not found")))

    def do_POST(self):
        if not self._allowed():
            return self._send(403, json.dumps(dict(error="This page may not use the Tally bridge")))
        if not self.path.startswith("/tally"):
            return self._send(404, json.dumps(dict(error="not found")))
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            text = tally_post(body)
        except Exception as e:  # noqa: BLE001
            return self._send(502, json.dumps(dict(error=f"Tally is not answering on {TALLY}: {e}")))
        self._send(200, text, "text/xml; charset=utf-8")


def install_startup():
    """A small .bat in the Windows Startup folder -> the bridge starts with Windows (minimised)."""
    start = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
    if not os.path.isdir(start):
        sys.exit("Startup folder not found (Windows only).")
    me = os.path.abspath(__file__)
    path = os.path.join(start, "SDEW Tally bridge.bat")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f'@echo off\nstart "SDEW Tally bridge" /min "{sys.executable}" "{me}"\n')
    print(f"Added to Windows startup: {path}")


def main(argv):
    global PORT, TALLY
    if "--port" in argv:
        PORT = int(argv[argv.index("--port") + 1])
    if "--tally" in argv:
        TALLY = argv[argv.index("--tally") + 1].rstrip("/")
    extra = os.environ.get("HUB_ORIGINS", "")
    ORIGINS.update(o.strip().rstrip("/") for o in extra.split(",") if o.strip())
    if "--startup" in argv:
        install_startup()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Bridge)
    print(f"SDEW Tally bridge on http://localhost:{PORT}  ->  Tally {TALLY}   (computer {socket.gethostname()})")
    print("Keep this window open. The website's 'Pull from Tally' now reads THIS computer's Tally.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
