"""TAFE purchase orders: PO line item number for (Order No., Part No.).

In the hub the DQMS module and the Supplementary Bill module read the SAME po_headers / po_items
tables - a PO uploaded anywhere in the hub is used by both. Line items come from:
  1. a PO .htm or TAFE PO export (uploaded on any page - read by the Supplementary Bill reader)
  2. a line item typed by hand on the Create / POs page (line_overrides - always wins)
"""
from datetime import datetime

from ..db import get_db, one, rows


def _now():
    return datetime.now().isoformat(timespec="seconds")


def seed_if_empty(con):
    """Old app: copied POs from a JSON file. The hub shares the POs - nothing to do."""
    return None


def import_supp_bill():
    """Old app: copied the Supplementary Bill app's POs. In the hub they are the same tables already."""
    return dict(pos=one("SELECT COUNT(*) n FROM po_headers")["n"], items=one("SELECT COUNT(*) n FROM po_items")["n"],
                shared=True)


def import_htm(name, data):
    """A PO .htm dropped on the DQMS page: stored once, in the shared PO tables (full price blocks)."""
    from ...supp.services import po_parser
    html = data.decode("utf-8", errors="ignore")
    if not po_parser.looks_like_po(html):
        return None
    from ...supp.services.ingest import ingest
    r = ingest(name, data)     # raises ApiError with a clear message when the PO cannot be read
    return dict(kind="po", po_no=r.get("po_no"), items=r.get("items"), plant=r.get("plant"), message=r.get("message"))


def lookup_maps():
    """-> (items {(po, part): row}, overrides {(po, part): item}, parts {part: [rows in any PO]}, plants {po: plant})"""
    items, parts = {}, {}
    for r in rows("SELECT po_no, part, item, descr FROM po_items"):
        items[(r["po_no"], r["part"])] = r
        parts.setdefault(r["part"], []).append(r)
    ov = {(r["po_no"], r["part"]): r["item"] for r in rows("SELECT po_no, part, item FROM line_overrides")}
    plants = {r["po_no"]: r["plant"] for r in rows("SELECT po_no, plant FROM po_headers")}
    return items, ov, parts, plants


def set_override(po_no, part, item):
    con = get_db()
    if item in (None, ""):
        con.execute("DELETE FROM line_overrides WHERE po_no=? AND part=?", (po_no, part))
    else:
        con.execute("INSERT INTO line_overrides(po_no,part,item,updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(po_no,part) DO UPDATE SET item=excluded.item, updated_at=excluded.updated_at",
                    (po_no, part, int(item), _now()))
    con.commit()
