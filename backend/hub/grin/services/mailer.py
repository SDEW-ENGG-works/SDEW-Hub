"""GRIN reminder mails: one mail per buyer with every invoice still Not GRINed.

Rules
  * only invoices with status 'Not GRINed' (older than wait_days, no GRIN) and not put on hold;
  * an invoice is not mailed again within resend_days of its last reminder;
  * once an invoice has had escalate_after reminders, the escalation CC (Settings) is added;
  * 'Send test mails to' (Settings) sends every mail to that one address instead - use it first.
Sending uses SMTP from the hub's .env:
  SMTP_HOST=smtp.gmail.com  SMTP_PORT=587  SMTP_USER=...  SMTP_PASS=<app password>  MAIL_FROM=...
Without SMTP a mail can still be downloaded as .eml and sent from Outlook / Gmail by hand.
"""
import html
import json
import smtplib
import ssl
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from ... import config
from ..db import get_db, log, one, rows
from . import status as st
from .defaults import load_settings


def smtp_settings():
    env = config.read_env()
    host = env.get("SMTP_HOST", "")
    return dict(host=host, port=int(env.get("SMTP_PORT") or 587), user=env.get("SMTP_USER", ""),
                password=env.get("SMTP_PASS", ""), sender=env.get("MAIL_FROM") or env.get("SMTP_USER", ""),
                ssl=str(env.get("SMTP_SSL", "")).lower() in ("1", "true", "yes"),
                ready=bool(host and env.get("SMTP_USER") and env.get("SMTP_PASS")))


def _dmy(iso):
    return f"{iso[8:10]}-{iso[5:7]}-{iso[0:4]}" if iso and len(iso) >= 10 else (iso or "")


def _parts(r):
    ps = [f"{p['part']} x {p['qty']:g}" for p in r["parts"] if p["part"]]
    return ", ".join(ps[:4]) + (f" + {len(ps) - 4} more" if len(ps) > 4 else "")


def plan(as_of=None, only_buyer=None, inv_keys=None):
    """Drafts to send now. inv_keys: send exactly these invoices (still must be Not GRINed)."""
    s = load_settings()
    data = st.build(as_of)
    today = date.fromisoformat(data["as_of"])
    blist = {b["id"]: b for b in st.buyers()}
    groups = {}
    skipped = []
    for r in data["rows"]:
        if r["status"] != st.NOT_GRINED:
            continue
        if inv_keys is not None and r["inv_key"] not in inv_keys:
            continue
        if r["hold"]:
            skipped.append(dict(inv_no=r["inv_no"], why="on hold"))
            continue
        if inv_keys is None and r["last_reminder"]:
            last = date.fromisoformat(r["last_reminder"][:10])
            if (today - last).days < s["resend_days"]:
                skipped.append(dict(inv_no=r["inv_no"], why=f"reminded on {_dmy(r['last_reminder'][:10])}"))
                continue
        key = r["buyer_id"] or f"plant:{r['plant']}"
        if only_buyer and str(key) != str(only_buyer):
            continue
        groups.setdefault(key, []).append(r)
    drafts = []
    for key, invs in groups.items():
        b = blist.get(key) if isinstance(key, int) else None
        plant = invs[0]["plant"]
        to = (b["email"] if b else "") or ""
        cc = [c.strip() for c in ((b["cc"] if b else "") or "").replace(";", ",").split(",") if c.strip()]
        esc = [r["inv_no"] for r in invs if r["reminders"] >= s["escalate_after"]]
        if esc and s["escalate_cc"]:
            cc += [c.strip() for c in s["escalate_cc"].replace(";", ",").split(",") if c.strip() and c.strip() not in cc]
        name = (b["name"] if b else "") or "Sir/Madam"
        plants = sorted({r["plant"] for r in invs})
        subject = s["mail_subject"].format(count=len(invs), plant="/".join(plants), name=name)
        intro = s["mail_intro"].format(name=name, plant="/".join(plants), count=len(invs))
        drafts.append(dict(key=str(key), buyer_id=b["id"] if b else None, buyer=(b["name"] if b else "") or "",
                           plant=plant, to=to, cc=", ".join(cc), subject=subject, intro=intro,
                           signature=s["signature"], escalated=esc,
                           invoices=[dict(inv_key=r["inv_key"], inv_no=r["inv_no"], inv_date=r["inv_date"],
                                          order_no=r["order_no"], parts=_parts(r), qty=r["qty"], amount=r["amount"],
                                          age=r["age"], reminders=r["reminders"], plant=r["plant"]) for r in invs],
                           problem="" if to else f"No buyer e-mail for plant {plant} - add one on the Buyers tab"))
    drafts.sort(key=lambda d: (d["problem"] != "", d["plant"], d["buyer"]))
    for d in drafts:
        d["html"], d["text"] = render(d)
    return dict(drafts=drafts, skipped=skipped, smtp=_public_smtp(), test_to=s["test_to"], as_of=data["as_of"])


def _public_smtp():
    m = smtp_settings()
    return dict(ready=m["ready"], host=m["host"], sender=m["sender"])


def render(d):
    head = ["Invoice No", "Invoice Date", "PO No", "Parts", "Qty", "Value (Rs)", "Days", "Reminder"]
    trs = []
    lines = []
    for i in d["invoices"]:
        cells = [i["inv_no"], _dmy(i["inv_date"]), i["order_no"] or "", i["parts"], f"{i['qty']:g}" if i["qty"] else "",
                 f"{i['amount']:,.2f}" if i["amount"] else "", str(i["age"] or ""), str(i["reminders"] + 1)]
        trs.append("<tr>" + "".join(
            f'<td style="border:1px solid #cbd5e1;padding:4px 8px;{"text-align:right;" if n in (4, 5, 6, 7) else ""}">'
            f"{html.escape(c)}</td>" for n, c in enumerate(cells)) + "</tr>")
        lines.append(" | ".join(cells))
    total = sum(i["amount"] or 0 for i in d["invoices"])
    intro_html = html.escape(d["intro"]).replace("\n", "<br>")
    sig_html = html.escape(d["signature"]).replace("\n", "<br>")
    body = f"""<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#0f172a">
<p>{intro_html}</p>
<table style="border-collapse:collapse;font-size:12px">
<thead><tr>{''.join(f'<th style="border:1px solid #cbd5e1;padding:4px 8px;background:#f1f5f9;text-align:left">{h}</th>' for h in head)}</tr></thead>
<tbody>{''.join(trs)}</tbody>
<tfoot><tr><td colspan="5" style="border:1px solid #cbd5e1;padding:4px 8px;font-weight:bold">Total ({len(d['invoices'])} invoices)</td>
<td style="border:1px solid #cbd5e1;padding:4px 8px;text-align:right;font-weight:bold">{total:,.2f}</td><td colspan="2" style="border:1px solid #cbd5e1"></td></tr></tfoot>
</table>
<p>{sig_html}</p></div>"""
    text = f"{d['intro']}\n\n" + " | ".join(head) + "\n" + "\n".join(lines) + \
        f"\n\nTotal ({len(d['invoices'])} invoices): Rs {total:,.2f}\n\n{d['signature']}\n"
    return body, text


def _message(d, sender, to, cc):
    msg = EmailMessage()
    msg["Subject"] = d["subject"]
    msg["From"] = sender or "me@localhost"
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="sdew-hub")
    msg.set_content(d["text"])
    msg.add_alternative(d["html"], subtype="html")
    return msg


def _record(d, status_, to, cc, error=""):
    con = get_db()
    now = datetime.now().isoformat(timespec="seconds")
    cur = con.execute("INSERT INTO gp_mails(created_at, sent_at, buyer_id, buyer, to_addr, cc, subject, body, invoices, "
                      "status, error) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (now, now if status_ == "Sent" else "", d.get("buyer_id"), d.get("buyer") or d.get("plant"), to, cc,
                       d["subject"], d["html"], json.dumps([i["inv_no"] for i in d["invoices"]]), status_, error))
    mid = cur.lastrowid
    for i in d["invoices"]:
        con.execute("INSERT OR REPLACE INTO gp_mail_invoices(mail_id, inv_key, sent_at) VALUES(?,?,?)",
                    (mid, i["inv_key"], now if status_ == "Sent" else ""))
    con.commit()
    st.invalidate()
    return mid


def send(drafts):
    s = load_settings()
    m = smtp_settings()
    if not m["ready"]:
        raise RuntimeError("Mail is not set up: put SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS and MAIL_FROM in the "
                           "hub's .env file (Gmail: smtp.gmail.com, 587, an App Password) and restart the hub.")
    results = []
    server = None
    try:
        if m["ssl"] or m["port"] == 465:
            server = smtplib.SMTP_SSL(m["host"], m["port"], context=ssl.create_default_context(), timeout=60)
        else:
            server = smtplib.SMTP(m["host"], m["port"], timeout=60)
            server.ehlo()
            if server.has_extn("starttls"):
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
        if server.has_extn("auth"):
            server.login(m["user"], m["password"])
        for d in drafts:
            to, cc = d["to"], d["cc"]
            if s["test_to"]:
                to, cc = s["test_to"], ""
            if not to:
                results.append(dict(key=d["key"], ok=False, error=d["problem"] or "No e-mail address"))
                continue
            try:
                server.send_message(_message(d, m["sender"], to, cc))
                mid = _record(d, "Sent" if not s["test_to"] else "Test", to, cc)
                results.append(dict(key=d["key"], ok=True, mail_id=mid, to=to, invoices=len(d["invoices"])))
            except Exception as e:  # noqa: BLE001
                _record(d, "Failed", to, cc, str(e))
                results.append(dict(key=d["key"], ok=False, error=str(e)))
    finally:
        if server:
            try:
                server.quit()
            except Exception:  # noqa: BLE001
                pass
    n = sum(1 for r in results if r["ok"])
    log("grin", "GRIN reminders", f"{n} mail(s) {'(test)' if s['test_to'] else 'sent'}")
    return results


def eml(d):
    """The mail as a .eml file (opens as a ready draft in Outlook)."""
    s = load_settings()
    m = smtp_settings()
    to, cc = (s["test_to"], "") if s["test_to"] else (d["to"], d["cc"])
    msg = _message(d, m["sender"], to or "", cc)
    msg["X-Unsent"] = "1"
    _record(d, "Draft", to, cc)
    return msg.as_bytes()


def mark_sent(mail_id):
    con = get_db()
    now = datetime.now().isoformat(timespec="seconds")
    if not one("SELECT id FROM gp_mails WHERE id=?", (mail_id,)):
        raise ValueError("Mail not found")
    con.execute("UPDATE gp_mails SET status='Sent', sent_at=? WHERE id=?", (now, mail_id))
    con.execute("UPDATE gp_mail_invoices SET sent_at=? WHERE mail_id=?", (now, mail_id))
    con.commit()
    st.invalidate()


def history(limit=200):
    out = rows("SELECT id, created_at, sent_at, buyer, to_addr, cc, subject, invoices, status, error FROM gp_mails "
               "ORDER BY id DESC LIMIT ?", (limit,))
    for r in out:
        r["invoices"] = json.loads(r["invoices"] or "[]")
    return out


def since(days):
    return (date.today() - timedelta(days=days)).isoformat()
