from datetime import datetime

from ..db import get_db, rows
from ..http import ApiError, route
from ..services.packing import part_key


@route("GET", r"/api/parts")
def list_parts(req):
    return rows("SELECT part, type, part_name, source, updated_at FROM part_types ORDER BY part")


@route("PUT", r"/api/parts")
def put_part(req):
    b = req.json
    part = part_key(b.get("part")) or str(b.get("part") or "").strip().upper()
    code = str(b.get("type") or "").strip()
    if not part or not code:
        raise ApiError("Part and CHEP size are needed")
    con = get_db()
    con.execute("INSERT INTO part_types(part,type,part_name,source,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(part) DO UPDATE SET type=excluded.type, part_name=COALESCE(NULLIF(excluded.part_name,''), part_types.part_name), "
                "source='manual', updated_at=excluded.updated_at",
                (part, code, str(b.get("part_name") or "").strip(), "manual", datetime.now().isoformat(timespec="seconds")))
    con.commit()
    return dict(ok=True)


@route("DELETE", r"/api/parts/(?P<part>[\w\-]+)")
def delete_part(req):
    con = get_db()
    con.execute("DELETE FROM part_types WHERE part=?", (req.params["part"],))
    con.commit()
    return dict(ok=True)
