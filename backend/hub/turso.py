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

    def _post(self, requests):
        body = json.dumps({"requests": requests + [{"type": "close"}]}).encode("utf-8")
        req = urllib.request.Request(self.endpoint, data=body, method="POST", headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise TursoError(f"Turso HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
        except urllib.error.URLError as e:
            raise TursoError(f"Turso not reachable: {e.reason}")
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

    def executemany(self, sql, seq):
        for args in seq:
            self.execute(sql, args)

    def executescript(self, script):
        for stmt in (s.strip() for s in script.split(";")):
            if stmt:
                self.execute(stmt)
        self._flush()

    def commit(self):
        self._flush()

    def close(self):
        self.commit()
