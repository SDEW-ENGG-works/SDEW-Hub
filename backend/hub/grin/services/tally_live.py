"""Tally, live: the hub keeps its copy of Tally up to date by itself, so Ore mirrors Tally within minutes.

TallyPrime cannot tell anyone it changed, so the hub asks. Tally numbers every change: each voucher and master
has an AlterID, and the company carries the last one given out (AltVchID for vouchers, AltMstID for groups,
ledgers and stock items). Every TALLY_LIVE_SECONDS (120) the PC hub, for each Tally company:
  1. asks the company's AltVchID and AltMstID (a tiny request). Same as last time: nothing changed, done;
  2. vouchers changed: asks only the vouchers with AlterID above the last one seen, every type with every ledger
     line, and stores them exactly as the full pull does (TAFE invoices are picked out as before);
  3. masters or vouchers changed: reads the groups and the ledgers with their balance today (Tally's trial
     balance), so new ledgers, moved ledgers and the stock ledger reach Ore too.
Once a night (TALLY_LIVE_NIGHT_HOUR, 23 by default), and on "Check deleted now":
  4. the ledger balances on the last month end and the stock summary today;
  5. vouchers deleted in Tally: for every month from the GRIN "from date" (1 Apr 2026) it lists the GUIDs Tally
     has and marks the hub's vouchers that are gone as deleted (and cancelled), so Ore reverses them. A month
     where Tally answers with nothing, or with fewer than half the vouchers the hub holds, is left alone and
     reported: an empty answer is far likelier to be a Tally hiccup than a month of deletions.
The first check after this update only notes Tally's current numbers: do one full Pull from Tally first.
Runs on the PC hub only (Tally is on this PC). TALLY_LIVE=0 in .env turns it off. A manual pull pauses it.
Every check leaves its result in settings "grin.tally_live" for the Sources page and for Ore.
"""
import html
import os
import re
import threading
import time
import traceback
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

from ... import config
from . import tally
from . import tally_masters

STATE_KEY = "tally_live"
_lock = threading.Lock()
_on = False


# ----------------------------------------------------------------------------- settings
def _env(name, default):
    return str(os.environ.get(name) or config.read_env().get(name) or default).strip()


def enabled():
    return _env("TALLY_LIVE", "1").lower() not in ("0", "false", "no", "off")


def seconds():
    try:
        return max(30, int(_env("TALLY_LIVE_SECONDS", "120")))
    except ValueError:
        return 120


def night_hour():
    try:
        return min(23, max(0, int(_env("TALLY_LIVE_NIGHT_HOUR", "23"))))
    except ValueError:
        return 23


def live_from():
    from .defaults import load_settings
    try:
        return date.fromisoformat(load_settings().get("from_date") or "2026-04-01")
    except ValueError:
        return date(2026, 4, 1)


def companies():
    from .defaults import load_settings
    out = []
    for c in load_settings().get("tally_companies") or [""]:
        out.append(c.get("name", "") if isinstance(c, dict) else (c or ""))
    return out or [""]


def load_state():
    from ..db import get_setting
    return get_setting(STATE_KEY, {}) or {}


def save_state(state):
    from ..db import set_setting
    set_setting(STATE_KEY, state)


# ----------------------------------------------------------------------------- requests
def _co(company):
    return f"<SVCURRENTCOMPANY>{html.escape(company)}</SVCURRENTCOMPANY>" if company else ""


def counters_request(company):
    return f"""<ENVELOPE>
 <HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>SDEWHubLive</ID></HEADER>
 <BODY><DESC>
  <STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>{_co(company)}</STATICVARIABLES>
  <TDL><TDLMESSAGE>
   <COLLECTION NAME="SDEWHubLive" ISMODIFY="No"><TYPE>Company</TYPE><FETCH>Name, AltVchID, AltMstID</FETCH></COLLECTION>
  </TDLMESSAGE></TDL>
 </DESC></BODY>
</ENVELOPE>"""


def _period():
    return live_from(), date(date.today().year + 1, 3, 31)


def changed_request(company, after):
    """Every voucher (any type, any date in the books) with AlterID above `after`, fields as tally.collection_request."""
    d1, d2 = _period()
    return f"""<ENVELOPE>
 <HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>SDEWHubChanged</ID></HEADER>
 <BODY><DESC>
  <STATICVARIABLES>
   <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>{_co(company)}
   <SVFROMDATE TYPE="Date">{tally._tdate(d1)}</SVFROMDATE><SVTODATE TYPE="Date">{tally._tdate(d2)}</SVTODATE>
  </STATICVARIABLES>
  <TDL><TDLMESSAGE>
   <COLLECTION NAME="SDEWHubChanged" ISMODIFY="No">
    <TYPE>Voucher</TYPE>
    <FETCH>Date, VoucherNumber, VoucherTypeName, PartyLedgerName, Reference, IsCancelled, IsOptional</FETCH>
    <FETCH>GUID, Narration, AlterID</FETCH>
    <FETCH>AllInventoryEntries.*, LedgerEntries.*, AllLedgerEntries.*, InvoiceOrderList.*</FETCH>
    <FILTER>SDEWHubAfter</FILTER>
   </COLLECTION>
   <SYSTEM TYPE="Formulae" NAME="SDEWHubAfter">$AlterID &gt; {int(after)}</SYSTEM>
  </TDLMESSAGE></TDL>
 </DESC></BODY>
</ENVELOPE>"""


def guids_request(company, d1, d2):
    return f"""<ENVELOPE>
 <HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>SDEWHubGuids</ID></HEADER>
 <BODY><DESC>
  <STATICVARIABLES>
   <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>{_co(company)}
   <SVFROMDATE TYPE="Date">{tally._tdate(d1)}</SVFROMDATE><SVTODATE TYPE="Date">{tally._tdate(d2)}</SVTODATE>
  </STATICVARIABLES>
  <TDL><TDLMESSAGE>
   <COLLECTION NAME="SDEWHubGuids" ISMODIFY="No"><TYPE>Voucher</TYPE><FETCH>GUID, Date</FETCH></COLLECTION>
  </TDLMESSAGE></TDL>
 </DESC></BODY>
</ENVELOPE>"""


# ----------------------------------------------------------------------------- reading answers
def _root(text):
    err = tally.tally_error(text)
    if err:
        raise RuntimeError(err)
    return ET.fromstring(tally.clean_xml(text))


def _int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group(0)) if m else None


def parse_counters(text):
    """-> (AltVchID, AltMstID) of the company in the answer (None when Tally does not send one)."""
    root = _root(text)
    for c in root.iter("COMPANY"):
        return _int(c.findtext("ALTVCHID")), _int(c.findtext("ALTMSTID"))
    return None, None


def parse_guids(text):
    root = _root(text)
    out = {}
    for v in root.iter("VOUCHER"):
        g = (v.findtext("GUID") or "").strip()
        if g:
            out[g] = tally._date(v.findtext("DATE"))
    return out


# ----------------------------------------------------------------------------- one company
def _store_changed(text, company, parties):
    """A changed-vouchers answer -> stored like the full pull. -> (vouchers kept, TAFE invoices, newest AlterID)."""
    vs = tally.parse_full(text)
    n = tally.store_full(vs, company)
    invs = [x for x in tally.parse_vouchers(text) if x["inv_date"]]
    sales = [x for x in invs if tally.is_sales(x, parties)]
    if sales:
        tally.store(sales, company)
    newest = max((v["alter_id"] for v in vs if v.get("alter_id")), default=None)
    return n, len(sales), newest


def check_company(url, company, st, parties, log=print):
    """One live check of one company; updates and returns its state dict."""
    st = dict(st or {})
    now = datetime.now().isoformat(timespec="seconds")
    vch, mst = parse_counters(tally.post(url, counters_request(company), timeout=30))
    st["checked_at"] = now
    st.pop("error", None)
    if vch is None and mst is None:
        raise RuntimeError("Tally did not send the company's change numbers (AltVchID / AltMstID)")
    first = "alt_vch" not in st
    if first:   # the first check notes where Tally is; the full Pull from Tally before it holds the rest
        st.update(alt_vch=vch or 0, alt_mst=mst or 0, since=now)
        log(f"{company or 'open company'}: live from Tally change no. {vch} (vouchers) / {mst} (masters)")
        return st
    if (vch is not None and vch < st.get("alt_vch", 0)) or (mst is not None and mst < st.get("alt_mst", 0)):
        # Tally's numbers went back: the company was restored from a backup or rewritten. Start again from here.
        st.update(alt_vch=vch or 0, alt_mst=mst or 0, since=now,
                  note="Tally's change numbers went back (company restored?). Do a full Pull from Tally once")
        log(f"{company or 'open company'}: {st['note']}")
        return st
    changed_v = vch is not None and vch > st.get("alt_vch", 0)
    changed_m = mst is not None and mst > st.get("alt_mst", 0)
    if not changed_v and not changed_m:
        return st
    kept = sales = 0
    if changed_v:
        text = tally.post(url, changed_request(company, st.get("alt_vch", 0)))
        kept, sales, newest = _store_changed(text, company, parties)
        st["alt_vch"] = max(vch, newest or 0)
    if changed_m:
        st["alt_mst"] = mst
    # balances today (Tally's trial balance) and, when masters changed, the group list too
    try:
        if changed_m:
            tally_masters.ingest("groups", tally.post(url, tally_masters.requests_for("groups", company)[0]), company)
        on = date.today()
        last = ""
        for xml in tally_masters.requests_for("ledgers", company, on):
            try:
                tally_masters.ingest("ledgers", tally.post(url, xml), company, on.isoformat())
                last = ""
                break
            except Exception as e:  # noqa: BLE001
                last = str(e)
        if last:
            log(f"{company or 'open company'}: ledger balances not read ({last[:120]})")
    except Exception as e:  # noqa: BLE001 - the vouchers are kept even when the ledgers fail
        log(f"{company or 'open company'}: groups/ledgers not read ({str(e)[:150]})")
    st["changed_at"] = now
    st["last"] = dict(vouchers=kept, invoices=sales, masters=changed_m, at=now)
    log(f"{company or 'open company'}: {kept} changed vouchers ({sales} TAFE invoices)"
        + (", masters changed" if changed_m else ""))
    return st


def deleted_check(url, company, log=print):
    """Mark the hub's vouchers that Tally no longer has as deleted (and cancelled). -> dict of counts."""
    from ..db import get_db, rows
    out = dict(months=0, deleted=0, skipped=[])
    d = live_from().replace(day=1)
    today = date.today()
    con = get_db()
    now = datetime.now().isoformat(timespec="seconds")
    while d <= today:
        end = (d + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        have = {r["vkey"]: r["guid"] for r in rows(
            "SELECT vkey, guid FROM gp_tally_vouchers WHERE COALESCE(company,'')=? AND vdate>=? AND vdate<=? "
            "AND COALESCE(deleted,0)=0 AND COALESCE(guid,'')<>''", (company, d.isoformat(), end.isoformat()))}
        if have:
            try:
                tally_guids = parse_guids(tally.post(url, guids_request(company, d, end)))
            except Exception as e:  # noqa: BLE001
                out["skipped"].append(f"{d:%b-%Y}: {str(e)[:80]}")
                d = end + timedelta(days=1)
                continue
            gone = [k for k, g in have.items() if g not in tally_guids]
            if gone and (not tally_guids or len(gone) * 2 > len(have)):
                out["skipped"].append(f"{d:%b-%Y}: Tally listed {len(tally_guids)} vouchers, the hub holds {len(have)}; "
                                      "left alone")
            elif gone:
                for k in gone:
                    con.execute("UPDATE gp_tally_vouchers SET deleted=1, cancelled=1, pulled_at=? WHERE vkey=?", (now, k))
                con.commit()
                out["deleted"] += len(gone)
            out["months"] += 1
        d = end + timedelta(days=1)
    log(f"{company or 'open company'}: deleted check of {out['months']} months, {out['deleted']} vouchers gone from Tally"
        + (f"; skipped {', '.join(out['skipped'])}" if out["skipped"] else ""))
    return out


def nightly(url, company, log=print):
    """Month end balances, stock today and the deleted check."""
    out = {}
    today = date.today()
    month_end = today.replace(day=1) - timedelta(days=1)
    for kind, on in (("ledgers", month_end), ("stock", today)):
        for xml in tally_masters.requests_for(kind, company, on):
            try:
                tally_masters.ingest(kind, tally.post(url, xml), company, on.isoformat())
                break
            except Exception as e:  # noqa: BLE001
                out[f"{kind}_error"] = str(e)[:150]
    out.update(deleted_check(url, company, log))
    return out


# ----------------------------------------------------------------------------- the loop
def tick(force_night=False, log=print):
    """One pass over every Tally company. Never raises; returns the state."""
    from .defaults import load_settings, plants
    if tally.STATUS.get("running"):
        return load_state()   # a manual Pull from Tally is running: let it finish
    with _lock:
        s = load_settings()
        url = s["tally_url"]
        parties = {p["party"] for p in plants()}
        state = load_state()
        for company in companies():
            key = company or "(open company)"
            st = state.get(key, {})
            try:
                st = check_company(url, company, st, parties, log)
                due = force_night or (datetime.now().hour >= night_hour()
                                      and st.get("night_on") != date.today().isoformat())
                if due and "alt_vch" in st:
                    st["night"] = nightly(url, company, log)
                    st["night_on"] = date.today().isoformat()
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "10061" in msg or "refused" in msg.lower() or "timed out" in msg.lower() or "urlopen" in msg.lower():
                    msg = "Tally is not answering (closed, or the company is not open)"
                st["error"] = msg[:300]
                st["error_at"] = datetime.now().isoformat(timespec="seconds")
            state[key] = st
        state["_meta"] = dict(seconds=seconds(), night_hour=night_hour(), on=True,
                              ticked_at=datetime.now().isoformat(timespec="seconds"))
        save_state(state)
        return state


def start_loop():
    global _on
    if _on or config.ON_VERCEL or not enabled():
        return False
    _on = True

    def loop():
        time.sleep(20)
        while True:
            try:
                tick(log=lambda m: print("[Tally live]", m))
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            time.sleep(seconds())

    threading.Thread(target=loop, daemon=True, name="tally-live").start()
    print(f"[Tally live] on: every {seconds()} s, deleted check after {night_hour()}:00")
    return True


def status():
    st = load_state()
    meta = st.pop("_meta", {})
    return dict(on=enabled(), seconds=seconds(), night_hour=night_hour(), ticked_at=meta.get("ticked_at"),
                companies=st)
