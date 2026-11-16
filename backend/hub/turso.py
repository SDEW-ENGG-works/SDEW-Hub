"""Tiny Turso (libSQL) client over HTTP - no packages to install.

Used on Vercel, where the disk is wiped after every request. It behaves like the
small part of sqlite3 the app uses: con.execute(sql, args) -> cursor with
fetchone / fetchall / lastrowid, con.commit(), con.executescript(sql).

Writes are queued and sent together in one HTTP request when something needs an
answer (a SELECT, lastrowid or commit), so saving 100 part sizes is one round trip.
"""
import base64
import json
import urllib.error
import urllib.request


class TursoError(Exception):
    pass


class Row(dict):
    """dict row that also allows row[0], like sqlite3.Row."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _arg(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode("ascii")}
    return {"type": "text", "value": str(v)}


def _val(v):
    t = v.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(v["value"])
    if t == "float":
        return float(v["value"])
    if t == "blob":
        s = v.get("base64", "")
        return base64.b64decode(s + "=" * (-len(s) % 4))
    return v.get("value")


class Cursor:
    def __init__(self, con):
        self._con = con
        self._result = None

    def _res(self):
        if self._result is None:
            self._con._flush()
        return self._result or {}

    @property
    def lastrowid(self):
        v = self._res().get("last_insert_rowid")
        return int(v) if v is not None else None

    @property
    def rowcount(self):
        return self._res().get("affected_row_count", -1)

    def fetchall(self):
        r = self._res()
        names = [c.get("name") for c in r.get("cols", [])]
        return [Row(zip(names, (_val(v) for v in row))) for row in r.get("rows", [])]

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    def __init__(self, url, token, timeout=60):
        url = url.strip()
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        self.endpoint = url.rstrip("/") + "/v2/pipeline"
        self.token = token.strip()
        self.timeout = timeout
        self._queue = []      # (cursor, request) not sent yet

    def _http(self):
        """One kept-open HTTPS connection per Connection: the TLS handshake (3 extra trips to the
        database's region) is paid once, not on every query."""
        import http.client
        import urllib.parse
        if getattr(self, "_conn", None) is None:
            u = urllib.parse.urlsplit(self.endpoint)
            cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
            self._conn = cls(u.hostname, u.port, timeout=self.timeout)
            self._path = u.path
        return self._conn

    def _post(self, requests):
        import http.client
        body = json.dumps({"requests": requests + [{"type": "close"}]}).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                   "Connection": "keep-alive"}
        for attempt in (1, 2):
            try:
                c = self._http()
                c.request("POST", self._path, body=body, headers=headers)
                resp = c.getresponse()
                raw = resp.read()
                if resp.status >= 400:
                    raise TursoError(f"Turso HTTP {resp.status}: {raw.decode('utf-8', 'replace')[:300]}")
                data = json.loads(raw.decode("utf-8"))
                break
            except TursoError:
                raise
            except (http.client.HTTPException, OSError) as e:   # server closed the kept-open connection
                try:
                    self._conn.close()
                except Exception:  # noqa: BLE001
                    pass
                self._conn = None
                if attempt == 2:
                    raise TursoError(f"Turso not reachable: {e}")
        return data["results"][:len(requests)]

    def _flush(self):
        if not self._queue:
            return
        queue, self._queue = self._queue, []
        results = self._post([q for _, q in queue])
        err = None
        for (cur, _), res in zip(queue, results):
            if res.get("type") == "error":
                err = err or res["error"].get("message", "error")
                cur._result = {}
            else:
                cur._result = res["response"]["result"]
        if err:
            raise TursoError(err)

    def execute(self, sql, args=()):
        cur = Cursor(self)
        if isinstance(args, dict):   # named parameters (:name) as sqlite3 allows
            stmt = {"sql": sql, "named_args": [{"name": k if k[:1] in ":@$" else ":" + k, "value": _arg(v)}
                                               for k, v in args.items()]}
        else:
            stmt = {"sql": sql, "args": [_arg(a) for a in args]}
        self._queue.append((cur, {"type": "execute", "stmt": stmt}))
        if sql.lstrip()[:6].upper() in ("SELECT", "PRAGMA"):
            cur._res()
        return cur

    # executemany: thousands of rows (e.g. every Tally ledger and its balance) used to go to Turso as one
    # statement per row in ONE request at commit - Turso then took longer than the 60 s read time-out
    # ("Turso not reachable: The read operation timed out"). Now a plain INSERT ... VALUES(?,..) is sent as
    # multi-row INSERTs (ROWS_PER_INSERT rows each), and the queue goes to Turso every SEND_EVERY statements.
    ROWS_PER_INSERT = 100
    SEND_EVERY = 20                 # multi-row inserts per request (= 2,000 rows)

    def executemany(self, sql, seq):
        import re
        seq = [tuple(a) for a in seq]
        m = re.match(r"(?is)^\s*(INSERT\s+(?:OR\s+\w+\s+)?INTO\s+.+?\)\s*VALUES)\s*(\(\s*\?(?:\s*,\s*\?)*\s*\))\s*;?\s*$", sql)
        if not m or len(seq) < 2:
            for i, args in enumerate(seq):
                self.execute(sql, args)
                if (i + 1) % 500 == 0:
                    self._flush()
            return
        head, one = m.group(1), m.group(2)
        width = one.count("?")
        per = max(1, min(self.ROWS_PER_INSERT, 30000 // max(width, 1)))
        for n, i in enumerate(range(0, len(seq), per), 1):
            part = seq[i:i + per]
            self.execute(f"{head} " + ", ".join([one] * len(part)), [v for row in part for v in row])
            if n % self.SEND_EVERY == 0:
                self._flush()

    def executescript(self, script):
        try:
            import sqlite3
            stmts = []
            buf = []
            for line in script.splitlines(True):
                buf.append(line)
                joined = "".join(buf)
                if sqlite3.complete_statement(joined):
                    stmt = joined.strip()
                    clean = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip().rstrip(";").strip()
                    if clean:
                        stmts.append(stmt)
                    buf = []
            if buf:
                leftover = "".join(buf).strip()
                clean = "\n".join(l for l in leftover.splitlines() if not l.strip().startswith("--")).strip().rstrip(";").strip()
                if clean:
                    stmts.append(leftover)
        except Exception:
            stmts = []
            for s in script.split(";"):
                stmt = s.strip()
                clean = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
                if clean:
                    stmts.append(stmt)
        for stmt in stmts:
            self.execute(stmt)
        self._flush()

    def commit(self):
        self._flush()

    def close(self):
        self.commit()
