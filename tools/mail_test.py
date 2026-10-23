"""Send one plain test mail with the SMTP settings in .env and say exactly where it fails.

    python tools\\mail_test.py someone@gmail.com
"""
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = {}
for line in open(os.path.join(ROOT, ".env"), encoding="utf-8-sig"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

host, port = env.get("SMTP_HOST", ""), int(env.get("SMTP_PORT") or 587)
if len(sys.argv) > 2:                       # python tools\mail_test.py to@x.com 587  -> try another port
    port = int(sys.argv[2])
user, pw = env.get("SMTP_USER", ""), env.get("SMTP_PASS", "")
sender = env.get("MAIL_FROM") or user
to = sys.argv[1] if len(sys.argv) > 1 else user
print(f"Server {host}:{port}  user {user}  from {sender}  to {to}  password {len(pw)} characters")

step = "connect"
try:
    if port == 465:
        s = smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30)
    else:
        s = smtplib.SMTP(host, port, timeout=30)
        s.ehlo()
        s.starttls(context=ssl.create_default_context())
        s.ehlo()
    step = "login"
    if pw != pw.strip() or " " in pw:
        print("  WARNING: the password has spaces - remove them in .env")
    s.login(user, pw)
    print("  login OK")
    step = "sender (MAIL FROM)"
    code, msg = s.mail(sender)
    if code != 250:
        raise smtplib.SMTPSenderRefused(code, msg, sender)
    print("  sender accepted")
    step = "recipient (RCPT TO)"
    code, msg = s.rcpt(to)
    if code not in (250, 251):
        raise smtplib.SMTPRecipientsRefused({to: (code, msg)})
    print("  recipient accepted")
    step = "message (DATA)"
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = "SDEW Hub test mail", sender, to
    m["Date"], m["Message-ID"] = formatdate(localtime=True), make_msgid(domain=sender.split("@")[-1])
    m.set_content("This is a test mail from SDEW Hub.")
    code, msg = s.data(m.as_bytes())
    if code != 250:
        raise smtplib.SMTPDataError(code, msg)
    s.quit()
    print("\nSENT - check the inbox (and spam) of", to)
except Exception as e:  # noqa: BLE001
    print(f"\nFAILED at step: {step}\n  {e!r}")
