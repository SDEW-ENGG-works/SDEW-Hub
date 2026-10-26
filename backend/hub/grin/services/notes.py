"""TAFE debit / credit notes: reading what notes_portal.py fetched, storing it, and the numbers for the page.

Document types (legend on TAFE Channel) and what we make of them:
    KD KE KF KG KQ KU KO   'DR intimation' (KD SEMB, KE MDUR, KF DDBR, KG HO, KQ transport, KU TGD, KO SBU North)
    KJ KI KK KL KV         'CR intimation' (credit - TAFE gives money back)
    ZK ZL                  'Tax invoice' TAFE raised on us - rejections scrapped on vendor account
What is inside a note (checked live 26-Oct-2026):
    rate difference  'Reason for Debit = Rate Difference / Invoice Number / Invoice Basic Rate per Unit / PO Basic Rate
                      per Unit / Diff Basic Value / GST Value / Net Value' (KE, KF)  or a ',,' table (KD)
    cash discount    fixed columns 'Doc. No. GRIN.date Invoice No. Amount Days CD Amount' (KG)
    rejection        Advice: Plant Code, Reason, Reference No. (our invoice), Rejection Doc. No + part lines (ZK)
"""
import html as _html
import re
from collections import defaultdict
from datetime import datetime
from html.parser import HTMLParser

from ..db import get_db, rows
from .norm import inv_key, iso, num

LABEL = {"KD": "Debit - SEMB", "KE": "Debit - Madurai", "KF": "Debit - Doddaballapur", "KG": "Debit - HO (cash discount)",
         "KQ": "Debit - transport", "KU": "Debit - TGD", "KO": "Debit - SBU North",
         "KJ": "Credit - Madurai", "KI": "Credit - SEMB", "KK": "Credit - Doddaballapur", "KL": "Credit - HO",
         "KV": "Credit - TGD", "ZK": "Tax invoice (rejection)", "ZL": "Tax invoice (rejection)"}
CREDIT_TYPES = {"KJ", "KI", "KK", "KL", "KV"}


def _now():
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------------------------------- the list
class _Rows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.cur, self.cell, self.depth = [], None, None, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            rid = re.search(r"asyncTableVendorDebit:__row(\w+)$", a.get("id") or "")
            if rid and rid.group(1) != "_template" and not rid.group(1).startswith("_"):
                self.cur = dict(rid=rid.group(1), cells=[])
                self.rows.append(self.cur)
        elif tag == "td" and self.cur is not None:
            self.cell = []
            self.cur["cells"].append(self.cell)

    def handle_endtag(self, tag):
        if tag == "tr":
            self.cur, self.cell = None, None

    def handle_data(self, d):
        if self.cell is not None and d.strip():
            self.cell.append(d.strip())


def parse_list(page):
    p = _Rows()
    p.feed(page)
    out, seen = [], set()
    for r in p.rows:
        cells = [" ".join(c).strip() for c in r["cells"]]
        i = next((k for k in range(len(cells) - 1)
                  if re.fullmatch(r"\d{6,}", cells[k]) and re.fullmatch(r"\d{2}/\d{2}/\d{4}", cells[k + 1])), None)
        if i is None or r["rid"] in seen:
            continue
        seen.add(r["rid"])
        rest = cells[i + 2:] + ["", "", "", ""]
        out.append(dict(rid=r["rid"], doc_no=cells[i], doc_date_dmy=cells[i + 1], doc_date=iso(cells[i + 1]),
                        doc_type=rest[0].upper(), grin_date=iso(rest[1]) if re.match(r"\d", rest[1] or "") else "",
                        label=rest[2]))
    return out


def _read_excel(xls):
    """Export as Excel -> {doc_no: dict(debit, credit, plant, reason, label)}"""
    if not xls:
        return {}
    import os
    import tempfile
    from ...supp.services.readers import sheets
    fd, path = tempfile.mkstemp(suffix=".xls")
    with os.fdopen(fd, "wb") as fh:
        fh.write(xls)
    out = {}
    try:
        for _, it in sheets(path):
            head = None
            for row in it:
                cells = [str(v).strip() if v is not None else "" for v in row]
                low = [c.lower() for c in cells]
                if head is None:
                    if any(c.startswith("document no") for c in low) and any("debit amount" in c for c in low):
                        head = {}
                        for k, c in enumerate(low):
                            for key, w in (("doc", "document no"), ("debit", "debit amount"), ("credit", "credit amount"),
                                           ("plant", "plant"), ("reason", "reason"), ("type", "document type"),
                                           ("label", "debit or credit")):
                                if c.startswith(w) and key not in head:
                                    head[key] = k
                    continue
                g = lambda k: cells[head[k]] if head.get(k) is not None and head[k] < len(cells) else ""  # noqa: E731
                doc = g("doc")
                if isinstance(doc, str) and doc.endswith(".0"):
                    doc = doc[:-2]
                if not re.fullmatch(r"\d{6,}", doc or ""):
                    continue
                plant = g("plant")
                out[(doc, g("type").upper())] = dict(debit=round(num(g("debit")), 2), credit=round(num(g("credit")), 2),
                                                     plant=plant[:-2] if plant.endswith(".0") else plant,
                                                     reason=g("reason"), label=g("label"))
            break
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return out


def store_list(lst, xls, d1, d2):
    amounts = _read_excel(xls)
    con = get_db()
    now = _now()
    for r in lst:
        a = amounts.get((r["doc_no"], r["doc_type"])) or next(
            (v for (d, _), v in amounts.items() if d == r["doc_no"]), {})
        con.execute(
            "INSERT INTO gp_dc_docs(doc_no, doc_type, doc_date, grin_date, label, debit, credit, plant, reason, rid, "
            "detail_status, listed_at) VALUES(?,?,?,?,?,?,?,?,?,?,'',?) ON CONFLICT(doc_no, doc_type) DO UPDATE SET "
            "doc_date=excluded.doc_date, grin_date=excluded.grin_date, label=excluded.label, rid=excluded.rid, "
            "debit=COALESCE(excluded.debit, gp_dc_docs.debit), credit=COALESCE(excluded.credit, gp_dc_docs.credit), "
            "plant=CASE WHEN excluded.plant<>'' THEN excluded.plant ELSE gp_dc_docs.plant END, "
            "reason=CASE WHEN excluded.reason<>'' THEN excluded.reason ELSE gp_dc_docs.reason END, "
            "listed_at=excluded.listed_at",
            (r["doc_no"], r["doc_type"], r["doc_date"], r["grin_date"], a.get("label") or r["label"],
             a.get("debit"), a.get("credit"), a.get("plant") or "", a.get("reason") or "", r["rid"], now))
    con.commit()
    return len(lst)


def pending(d1, d2):
    got = rows("SELECT doc_no, doc_type, doc_date, rid FROM gp_dc_docs WHERE doc_date BETWEEN ? AND ? "
               "AND COALESCE(detail_status,'') IN ('', 'error') ORDER BY doc_date, doc_no", (d1.isoformat(), d2.isoformat()))
    return [dict(g, doc_date_dmy=f"{g['doc_date'][8:10]}/{g['doc_date'][5:7]}/{g['doc_date'][:4]}") for g in got]


def listed_recently(d1, d2, minutes=30):
    """True when this month was listed in the last few minutes and every note in it is read (website repeat calls)."""
    from datetime import timedelta
    since = (datetime.now() - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    r = rows("SELECT COUNT(*) n, MIN(listed_at) l FROM gp_dc_docs WHERE doc_date BETWEEN ? AND ?",
             (d1.isoformat(), d2.isoformat()))
    return bool(r and r[0]["n"] and (r[0]["l"] or "") >= since and pending_count(d1, d2) == 0)


def pending_count(d1, d2):
    r = rows("SELECT COUNT(*) n FROM gp_dc_docs WHERE doc_date BETWEEN ? AND ? AND COALESCE(detail_status,'') IN ('', 'error')",
             (d1.isoformat(), d2.isoformat()))
    return r[0]["n"] if r else 0


# ------------------------------------------------------------------------------------------- one note
class _Text(HTMLParser):
    """Text pieces in order; <br> = new line; <tr>/<td> kept as table rows."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pieces, self.tables, self.skip, self.row, self.cell, self.pre = [], [], 0, None, None, []
        self.in_pre = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "br" and self.in_pre:
            self.pre.append("\n")
        elif tag == "pre":
            self.in_pre = True
        elif tag == "tr":
            self.row = []
            self.tables.append(self.row)
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
            self.row.append(self.cell)

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and self.in_pre:
            self.pre.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag == "pre":
            self.in_pre = False
            self.pre.append("\n<<END>>\n")
        elif tag in ("td", "th"):
            self.cell = None
        elif tag == "tr":
            self.row = None

    def handle_data(self, d):
        if self.skip:
            return
        if self.in_pre:
            self.pre.append(d)
            return
        if d.strip():
            self.pieces.append(d.strip())
            if self.cell is not None:
                self.cell.append(d.strip())


def _kv(text):
    out = {}
    for line in text.splitlines():
        m = re.match(r"\s*([A-Za-z][A-Za-z .()/]+?)\s*[:=]\s*(.*?)\s*$", line)
        if m:
            out.setdefault(m.group(1).strip().lower(), m.group(2).strip())
    return out


def parse_note(doc_type, page_html):
    """-> (lines, summary) for one note."""
    p = _Text()
    p.feed(_html.unescape(page_html) if "&lt;" in page_html[:500] else page_html)
    pre = "".join(p.pre).replace("<<END>>", "")
    lines = []
    if pre.strip():
        flat = re.sub(r"(\s*,,)+", " ", pre)              # some notes are prose padded with ',,'
        if re.search(r"excess claim against your Inv", flat, re.I):      # rate difference written as a letter
            m = lambda rx: (re.search(rx, flat, re.I | re.S) or [None, ""])[1]  # noqa: E731
            net = num(m(r"Total\s*:\s*([\d.,]+)"))
            basic = num(m(r"Value\s*:\s*([\d.,]+)"))
            gst = num(m(r"GST Tax\s*:\s*([\d.,]+)"))
            lines.append(dict(kind="Rate difference", inv_raw=m(r"Inv\.?\s*No\.?\s*([\w/-]+)"),
                              inv_date=iso(m(r"Inv\.?\s*No\.?\s*[\w/-]+\s+Dated\s+([\d.]+)")),
                              bill_rate=num(m(r"billed for the following at Rs\.?\s*([\d.,]+)")),
                              po_rate=num(m(r"instead of Rs\.?\s*([\d.,]+)")), po_no=m(r"P\.O\.\s*No\s*:?\s*(\w+)"),
                              grn_no=m(r"GRIN No\.?\s*(\w+)"), part=m(r"Part No\s*:\s*(\S+)"), qty=num(m(r"QTY\s*:\s*([\d.,]+)")),
                              diff_rate=num(m(r"Diff Rate\s*:\s*([\d.,]+)")), basic=basic, gst=gst,
                              net=round(net or basic + gst, 2)))
            return lines, dict(total=lines[0]["net"], reason="Rate difference")
        if re.search(r"premium freight", flat, re.I):        # freight TAFE paid for us
            amt = num((re.search(r"Amount Recovered\s*:\s*([\d.,]+)", flat) or [None, "0"])[1])
            tr = (re.search(r"Transporter\s*:\s*(.+?)(?:\n|Approval)", flat) or [None, ""])[1].strip()
            lines.append(dict(kind="Premium freight", net=amt, reason=f"Premium freight - {tr}"[:120],
                              ref_no=(re.search(r"Approval No\s*:\s*(\S+)", flat) or [None, ""])[1]))
            return lines, dict(total=amt, reason="Premium freight")
        if re.search(r"S\.?\s*No\.?\s+Material No\.?\s+Qty\s+PO Rate\s+Bill Rate", flat, re.I):   # rate table
            for ln in flat.splitlines():
                c = ln.split()
                if len(c) >= 9 and c[0].isdigit() and re.match(r"\d", c[2]):
                    lines.append(dict(kind="Rate difference", part=c[1], qty=num(c[2]), po_rate=num(c[3]), bill_rate=num(c[4]),
                                      diff_rate=num(c[5]), basic=num(c[6]), gst=num(c[7]), net=num(c[8])))
            inv = (re.search(r"Inv(?:oice)?\.?\s*No\.?\s*:?\s*([\w/-]+/\d\d-\d\d)", flat, re.I) or [None, ""])[1]
            for x in lines:
                x["inv_raw"] = inv
            return lines, dict(total=round(sum(x["net"] for x in lines), 2), reason="Rate difference")
        if re.search(r"\bFRT\b|freight", flat, re.I):        # freight TAFE paid (free delivery / rejected material moved)
            return [], dict(total=0, reason="Freight charges", text=flat.strip()[:3000])
        if ",," in pre and re.search(r"Invoice date,,", pre, re.I):   # KD: comma table
            for ln in pre.splitlines():
                c = [x.strip() for x in ln.split(",,")]
                if len(c) >= 7 and re.match(r"\d{1,2}\.\d{1,2}\.\d{4}", c[0]):
                    qty, bill, po = num(c[3]), num(c[4]), num(c[5])
                    lines.append(dict(kind="Rate difference", inv_raw=c[1], inv_date=iso(c[0]), part=c[2], qty=qty,
                                      bill_rate=bill, po_rate=po, diff_rate=round(bill - po, 4), basic=num(c[6])))
            tot = {}
            for ln in pre.splitlines():
                c = [x.strip() for x in ln.split(",,") if x.strip()]
                if len(c) == 2 and c[0] in ("CGST", "SGST", "IGST", "Total"):
                    tot[c[0]] = num(c[1])
            gst = tot.get("CGST", 0) + tot.get("SGST", 0) + tot.get("IGST", 0)
            basic = sum(x["basic"] for x in lines)
            for x in lines:                                 # GST shared by basic value
                x["gst"] = round(gst * x["basic"] / basic, 2) if basic else 0
                x["net"] = round(x["basic"] + x["gst"], 2)
            return lines, dict(total=tot.get("Total") or round(basic + gst, 2), reason="Rate difference")
        if re.search(r"CD\s+Amount", pre):                  # KG: cash discount table
            for ln in pre.splitlines():
                c = ln.split()
                if len(c) >= 6 and re.fullmatch(r"\d{6,}", c[0]) and re.fullmatch(r"\d{8}", c[1]):
                    g = c[1]
                    lines.append(dict(kind="Cash discount", grn_no=c[0], grn_date=f"{g[:4]}-{g[4:6]}-{g[6:]}",
                                      inv_raw=c[2], basic=num(c[3]), days=int(num(c[4])), net=num(c[5])))
            return lines, dict(total=round(sum(x["net"] for x in lines), 2), reason="Cash discount")
        blocks = re.split(r"(?=Plant Code\s*:)", pre)       # KE / KF: one or more 'key : value' blocks
        reason = (_kv(pre).get("reason for debit") or _kv(pre).get("reason for credit") or "").strip()
        if not reason:                                       # e.g. 'Rework Segregation', 'Reversing the Excess Credit'
            reason = next((ln.strip() for ln in pre.splitlines() if ln.strip()), "")[:80]
            reason = re.sub(r"\s+", " ", reason)
            kv = _kv(pre)
            if kv.get("part no"):
                lines.append(dict(kind=reason, part=kv.get("part no", ""), part_desc=kv.get("description", ""),
                                  qty=num(kv.get("qty")), net=num(kv.get("value")), ref_no=kv.get("cr no", "")))
        for b in blocks:
            kv = _kv(b)
            if "invoice number" not in kv:
                continue
            lines.append(dict(kind=reason or "Debit", plant=kv.get("plant code", ""), inv_raw=kv.get("invoice number", ""),
                              inv_date=iso(kv.get("invoice date", "")), grn_no=kv.get("gr no.", kv.get("gr no", "")),
                              grn_date=iso(kv.get("gr date", "")), part=kv.get("material code", ""),
                              part_desc=kv.get("material description", ""), qty=num(kv.get("gr quantity")),
                              po_no=kv.get("po ref no.", kv.get("po ref no", "")),
                              bill_rate=num(kv.get("invoice basic rate per unit")),
                              po_rate=num(kv.get("po basic rate per unit")),
                              diff_rate=num(kv.get("diff basic rate per unit")), basic=num(kv.get("diff basic value")),
                              gst=num(kv.get("gst value")), net=num(kv.get("net value"))))
        return lines, dict(total=round(sum(x["net"] for x in lines), 2), reason=reason or "Debit",
                           text=pre.strip()[:3000] if not lines else "")
    # Advice (ZK / ZL tax invoice): label / value pieces + the part table
    pcs = p.pieces
    labels = {"Plant Code": "plant", "Reason": "reason", "Transporter": "transporter", "Reference No.": "ref",
              "Rejection Doc. No": "rej", "Invoice Amount": "amount"}
    head = {}
    for k, piece in enumerate(pcs):
        key = labels.get(piece.rstrip(":").strip())
        if key and k + 1 < len(pcs) and pcs[k + 1].rstrip(":").strip() not in labels:
            head[key] = pcs[k + 1]
    if "amount" not in head:
        m = re.search(r"Invoice Amount\s*([\d,.]+)", " ".join(pcs))
        if m:
            head["amount"] = m.group(1)
    for r in p.tables:
        c = [" ".join(x).strip() for x in r]
        if len(c) >= 13 and c[0] and c[0] != "Part No" and re.search(r"\d", c[3] or ""):
            taxable = num(c[6])
            gst = num(c[8]) + num(c[10]) + num(c[12])
            lines.append(dict(kind="Rejection", plant=head.get("plant", ""), part=c[0], part_desc=c[1], ref_no=c[2],
                              qty=num(c[3]), bill_rate=num(c[4]), basic=taxable, gst=round(gst, 2),
                              net=round(taxable + gst, 2), inv_raw=head.get("ref", ""), reason=head.get("reason", ""),
                              rej_doc=head.get("rej", "")))
    if not lines and head.get("ref"):
        lines.append(dict(kind="Rejection", plant=head.get("plant", ""), inv_raw=head["ref"], reason=head.get("reason", ""),
                          rej_doc=head.get("rej", ""), net=num(head.get("amount"))))
    return lines, dict(total=num(head.get("amount")) or round(sum(x.get("net") or 0 for x in lines), 2),
                       reason=head.get("reason", "") or ("Rejection" if lines else ""),
                       text="" if lines else " ".join(pcs)[:3000])


COLS = ("kind", "plant", "inv_raw", "inv_date", "grn_no", "grn_date", "part", "part_desc", "qty", "po_no", "bill_rate",
        "po_rate", "diff_rate", "basic", "gst", "net", "days", "ref_no", "rej_doc", "reason")


def store_detail(row, page_html, error=""):
    con = get_db()
    now = _now()
    if error or not page_html:
        con.execute("UPDATE gp_dc_docs SET detail_status=?, error=?, read_at=? WHERE doc_no=? AND doc_type=?",
                    ("error" if error else "empty", error[:300], now, row["doc_no"], row["doc_type"]))
        con.commit()
        return 0
    lines, summ = parse_note(row["doc_type"], page_html)
    con.execute("DELETE FROM gp_dc_lines WHERE doc_no=? AND doc_type=?", (row["doc_no"], row["doc_type"]))
    for i, ln in enumerate(lines):
        vals = [ln.get(k) for k in COLS]
        con.execute(f"INSERT INTO gp_dc_lines(doc_no, doc_type, seq, inv_key, {', '.join(COLS)}) "
                    f"VALUES(?,?,?,?,{','.join('?' * len(COLS))})",
                    [row["doc_no"], row["doc_type"], i, inv_key(ln.get("inv_raw") or "")] + vals)
    con.execute("UPDATE gp_dc_docs SET detail_status=?, error='', note_total=?, note_reason=?, note_text=?, read_at=?, "
                "lines=? WHERE doc_no=? AND doc_type=?",
                ("ok" if lines else "empty", summ.get("total"), summ.get("reason") or "", summ.get("text") or "", now,
                 len(lines), row["doc_no"], row["doc_type"]))
    con.commit()
    return len(lines)


# ------------------------------------------------------------------------------------------- numbers for the page
def kind_of(doc_type, reason=""):
    t = (doc_type or "").upper()
    if t in ("ZK", "ZL"):
        return "Rejection"
    if t == "KG":
        return "Cash discount"
    if t in CREDIT_TYPES:
        return "Credit note"
    r = (reason or "").lower()
    if "rate" in r:
        return "Rate difference"
    if "premium freight" in r:
        return "Premium freight"
    if "freight" in r or "frt" in r:
        return "Freight charges"
    if "shortage" in r:
        return "Shortage"
    if "rework" in r or "segregation" in r:
        return "Rework / segregation"
    if "excess credit" in r or "revers" in r:
        return "Other debit"
    return "Rate difference" if t in ("KE", "KF", "KD", "KU", "KO") else "Other debit"


def summary(d1="", d2=""):
    where, args = "", []
    if d1:
        where += " AND doc_date >= ?"
        args.append(d1)
    if d2:
        where += " AND doc_date <= ?"
        args.append(d2)
    docs = rows(f"SELECT * FROM gp_dc_docs WHERE 1=1 {where} ORDER BY doc_date DESC, doc_no DESC", args)
    paid_refs = defaultdict(list)
    for p in rows("SELECT pv, pv_date, ref_doc, debit FROM gp_pay_lines WHERE debit > 0"):
        paid_refs[str(p["ref_doc"]).lstrip("0")].append(p)
    by_month = defaultdict(lambda: defaultdict(lambda: dict(n=0, amount=0.0)))
    by_kind = defaultdict(lambda: dict(n=0, amount=0.0, deducted=0.0))
    out = []
    for d in docs:
        amt = d["debit"] if d["debit"] else (d["note_total"] or 0)
        if d["doc_type"] in CREDIT_TYPES:
            amt = -(d["credit"] or d["note_total"] or 0)
        k = kind_of(d["doc_type"], d["note_reason"] or d["reason"])
        pr = paid_refs.get(str(d["doc_no"]).lstrip("0")) or []
        by_month[d["doc_date"][:7]][k]["n"] += 1
        by_month[d["doc_date"][:7]][k]["amount"] += amt
        by_kind[k]["n"] += 1
        by_kind[k]["amount"] += amt
        if pr:
            by_kind[k]["deducted"] += amt
        out.append(dict(doc_no=d["doc_no"], doc_type=d["doc_type"], type_label=LABEL.get(d["doc_type"], d["doc_type"]),
                        kind=k, doc_date=d["doc_date"], grin_date=d["grin_date"], plant=d["plant"],
                        reason=d["note_reason"] or d["reason"], amount=round(amt, 2), lines=d["lines"],
                        status=d["detail_status"] or "", pv=", ".join(sorted({x["pv"] for x in pr})),
                        pv_date=max((x["pv_date"] for x in pr), default="")))
    months = [dict(month=m, kinds={k: dict(n=v["n"], amount=round(v["amount"], 2)) for k, v in ks.items()},
                   total=round(sum(v["amount"] for v in ks.values()), 2)) for m, ks in sorted(by_month.items(), reverse=True)]
    return dict(docs=out, months=months,
                kinds={k: dict(n=v["n"], amount=round(v["amount"], 2), deducted=round(v["deducted"], 2))
                       for k, v in by_kind.items()},
                total=round(sum(v["amount"] for v in by_kind.values()), 2),
                unread=sum(1 for d in docs if (d["detail_status"] or "") in ("", "error")),
                range=dict(first=min((d["doc_date"] for d in docs), default=""),
                           last=max((d["doc_date"] for d in docs), default="")))


def lines_for(kind="", q="", d1="", d2="", limit=3000):
    where, args = [], []
    if d1:
        where.append("d.doc_date >= ?")
        args.append(d1)
    if d2:
        where.append("d.doc_date <= ?")
        args.append(d2)
    if q:
        where.append("(l.inv_raw LIKE ? OR l.part LIKE ? OR l.part_desc LIKE ? OR d.doc_no LIKE ? OR l.po_no LIKE ?)")
        args += [f"%{q}%"] * 5
    sql = ("SELECT l.*, d.doc_date, d.plant AS doc_plant FROM gp_dc_lines l JOIN gp_dc_docs d "
           "ON d.doc_no=l.doc_no AND d.doc_type=l.doc_type" + (" WHERE " + " AND ".join(where) if where else "") +
           " ORDER BY d.doc_date DESC, l.doc_no, l.seq")
    out = []
    for r in rows(sql, args):
        k = kind_of(r["doc_type"], r["kind"])
        if kind and k != kind:
            continue
        out.append(dict(r, kind=k))
        if len(out) >= limit:
            break
    if kind in ("", "Rejection") and len(out) < limit:
        # rejections whose Advice TAFE did not give: amount / reason from the list, our invoice from the payment
        pay = {}
        for p in rows("SELECT ref_doc, inv_raw, inv_key, pv, pv_date FROM gp_pay_lines WHERE doc_type IN ('ZK','ZL')"):
            pay[str(p["ref_doc"]).lstrip("0")] = p
        w2, a2 = ["doc_type IN ('ZK','ZL')", "COALESCE(lines,0)=0"], []
        if d1:
            w2.append("doc_date >= ?")
            a2.append(d1)
        if d2:
            w2.append("doc_date <= ?")
            a2.append(d2)
        for d in rows(f"SELECT * FROM gp_dc_docs WHERE {' AND '.join(w2)} ORDER BY doc_date DESC", a2):
            p = pay.get(str(d["doc_no"]).lstrip("0")) or {}
            line = dict(doc_no=d["doc_no"], doc_type=d["doc_type"], seq=0, inv_key=p.get("inv_key") or "", kind="Rejection",
                        plant=d["plant"], inv_raw=p.get("inv_raw") or "", inv_date="", grn_no="", grn_date=d["grin_date"],
                        part="", part_desc="(TAFE gave no part detail)", qty=None, po_no="", bill_rate=None, po_rate=None,
                        diff_rate=None, basic=None, gst=None, net=d["debit"] or d["note_total"] or 0, days=None,
                        ref_no="", rej_doc="", reason=d["reason"] or d["note_reason"], doc_date=d["doc_date"],
                        doc_plant=d["plant"])
            if q and not any(q.lower() in str(line.get(f) or "").lower() for f in ("inv_raw", "doc_no")):
                continue
            out.append(line)
    return out


def by_invoice():
    """inv_key -> list of (kind, doc_no, net) - used by the Status page."""
    out = defaultdict(list)
    seen = set()
    for r in rows("SELECT inv_key, doc_no, doc_type, kind, net FROM gp_dc_lines WHERE inv_key<>''"):
        out[r["inv_key"]].append(dict(kind=kind_of(r["doc_type"], r["kind"]), doc_no=r["doc_no"], net=r["net"] or 0))
        seen.add(str(r["doc_no"]).lstrip("0"))
    for p in rows("SELECT ref_doc, inv_key, debit FROM gp_pay_lines WHERE doc_type IN ('ZK','ZL') AND debit > 0"):
        if p["inv_key"] and str(p["ref_doc"]).lstrip("0") not in seen:     # rejection known only from the payment
            out[p["inv_key"]].append(dict(kind="Rejection", doc_no=p["ref_doc"], net=p["debit"] or 0))
    return out
