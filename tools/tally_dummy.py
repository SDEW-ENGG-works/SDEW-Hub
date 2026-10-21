"""Puts DUMMY TAFE invoices into a Tally TEST company through Tally's XML server (port 9000),
so the GRIN & Payments "Pull from Tally" can be tested.

    python tools\\tally_dummy.py              list the companies open in Tally
    python tools\\tally_dummy.py create       create ledgers, stock items and 5 dummy Sales invoices
    python tools\\tally_dummy.py delete       delete the 5 dummy invoices again

Works only on a company whose name contains TEST (so the real books are never touched).
Create one first in Tally: Alt+K > Create > Name "SDEW GRIN TEST" > Accept.
Invoice numbers 99001/26-27 ... 99005/26-27 can never match a real TAFE GRIN.
"""
import os
import re
import sys
import urllib.request
from datetime import date, timedelta
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
URL = os.environ.get("TALLY_URL", "http://localhost:9000")

DBR = "Tractors and Farm Equipment Ltd - B"
MDU = "Tractors and Farm Equpment Ltd"
SEM = "Tractor and Farm Equpment Ltd - SEMBIUM"
OTHER = "SAKTHI ENTERPRISES"          # not TAFE -> the pull must leave it out
ITEMS = [("3247A01402 - ASSY LEVER SHUTTLE ACTUATOR", 96.58),
         ("1520A01501 - ASSY EXHAUST ELBOW", 1071.60),
         ("3227A07401 - ASSY BRACKET", 395.70)]


def invoices():
    # Tally Educational mode only allows the 1st, 2nd and 31st of a month
    return [
        # no, date, party, PO, [(item, qty)], what the hub should show
        ("99001/26-27", date(2026, 10, 1), DBR, "1010016503", [(0, 50)], "Not GRINed (old, no GRIN)"),
        ("99002/26-27", date(2026, 10, 2), MDU, "1030000676", [(1, 10)], "Not GRINed (old, no GRIN)"),
        ("99003/26-27", date(2026, 10, 2), DBR, "1010017137", [(2, 27), (0, 20)], "Not GRINed, 2 parts"),
        ("99004/26-27", date(2026, 10, 1), SEM, "2010032150", [(0, 5)], "Not GRINed (SEMBIUM)"),
        ("99005/26-27", date(2026, 10, 2), OTHER, "", [(0, 3)], "NOT pulled (not a TAFE party)"),
    ]


def post(xml):
    req = urllib.request.Request(URL, data=xml.encode("utf-8"), headers={"Content-Type": "text/xml"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=60) as r:
        raw = r.read()
    from hub.grin.services.tally import decode
    return decode(raw)


def companies():
    from hub.grin.services.tally import COMPANIES_REQUEST, clean_xml
    text = clean_xml(post(COMPANIES_REQUEST))
    return re.findall(r'<COMPANY NAME="([^"]+)"', text) or re.findall(r"<NAME>([^<]+)</NAME>", text)


def envelope(company, report, body):
    return (f"<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>"
            f"<REQUESTDESC><REPORTNAME>{report}</REPORTNAME><STATICVARIABLES>"
            f"<SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC>"
            f"<REQUESTDATA>{body}</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")


def result(text, what):
    nums = {k: re.search(f"<{k}>(\\d+)</{k}>", text) for k in ("CREATED", "ALTERED", "DELETED", "ERRORS", "EXCEPTIONS")}
    nums = {k: int(v.group(1)) for k, v in nums.items() if v}
    errs = re.findall(r"<LINEERROR>(.*?)</LINEERROR>", text, re.S)
    print(f"  {what}: {nums or text[:300]}")
    for e in errs:
        print(f"    Tally says: {e.strip()}")
    return nums


def masters_xml():
    m = ['<TALLYMESSAGE xmlns:UDF="TallyUDF"><UNIT NAME="Nos" ACTION="Create"><NAME>Nos</NAME>'
         '<ISSIMPLEUNIT>Yes</ISSIMPLEUNIT></UNIT></TALLYMESSAGE>']
    for name, parent in [(DBR, "Sundry Debtors"), (MDU, "Sundry Debtors"), (SEM, "Sundry Debtors"),
                         (OTHER, "Sundry Debtors"), ("Sales", "Sales Accounts")]:
        m.append(f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><LEDGER NAME="{escape(name)}" ACTION="Create">'
                 f'<NAME.LIST><NAME>{escape(name)}</NAME></NAME.LIST><PARENT>{parent}</PARENT>'
                 f'<ISBILLWISEON>{"Yes" if parent == "Sundry Debtors" else "No"}</ISBILLWISEON></LEDGER></TALLYMESSAGE>')
    for name, _ in ITEMS:
        m.append(f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><STOCKITEM NAME="{escape(name)}" ACTION="Create">'
                 f'<NAME.LIST><NAME>{escape(name)}</NAME></NAME.LIST><BASEUNITS>Nos</BASEUNITS></STOCKITEM></TALLYMESSAGE>')
    return "".join(m)


def voucher_xml(no, d, party, po, lines):
    ds = d.strftime("%Y%m%d")
    inv, total = [], 0.0
    for idx, q in lines:
        name, rate = ITEMS[idx]
        amt = round(rate * q, 2)
        total += amt
        inv.append(f"<ALLINVENTORYENTRIES.LIST><STOCKITEMNAME>{escape(name)}</STOCKITEMNAME>"
                   f"<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><RATE>{rate:.2f}/Nos</RATE><AMOUNT>{amt:.2f}</AMOUNT>"
                   f"<ACTUALQTY> {q} Nos</ACTUALQTY><BILLEDQTY> {q} Nos</BILLEDQTY>"
                   f"<ACCOUNTINGALLOCATIONS.LIST><LEDGERNAME>Sales</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>"
                   f"<AMOUNT>{amt:.2f}</AMOUNT></ACCOUNTINGALLOCATIONS.LIST></ALLINVENTORYENTRIES.LIST>")
    order = (f"<INVOICEORDERLIST.LIST><BASICORDERDATE>{ds}</BASICORDERDATE>"
             f"<BASICPURCHASEORDERNO>{po}</BASICPURCHASEORDERNO></INVOICEORDERLIST.LIST>") if po else ""
    return (f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER VCHTYPE="Sales" ACTION="Create" OBJVIEW="Invoice Voucher View">'
            f"<DATE>{ds}</DATE><EFFECTIVEDATE>{ds}</EFFECTIVEDATE><VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>"
            f"<VOUCHERNUMBER>{no}</VOUCHERNUMBER><REFERENCE>{no}</REFERENCE>"
            f"<PARTYLEDGERNAME>{escape(party)}</PARTYLEDGERNAME><BASICBUYERNAME>{escape(party)}</BASICBUYERNAME>"
            f"<PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW><ISINVOICE>Yes</ISINVOICE>"
            f"<NARRATION>DUMMY invoice for testing the SDEW Hub Tally pull - delete after testing</NARRATION>{order}"
            f"<LEDGERENTRIES.LIST><LEDGERNAME>{escape(party)}</LEDGERNAME><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>"
            f"<ISPARTYLEDGER>Yes</ISPARTYLEDGER><AMOUNT>-{total:.2f}</AMOUNT>"
            f"<BILLALLOCATIONS.LIST><NAME>{no}</NAME><BILLTYPE>New Ref</BILLTYPE><AMOUNT>-{total:.2f}</AMOUNT></BILLALLOCATIONS.LIST>"
            f"</LEDGERENTRIES.LIST>{''.join(inv)}</VOUCHER></TALLYMESSAGE>"), total


def pick_company(names):
    tests = [n for n in names if "TEST" in n.upper()]
    if not tests:
        sys.exit("No company with TEST in its name is open in Tally.\n"
                 "Create one: Alt+K > Create > Name 'SDEW GRIN TEST' > Accept (Ctrl+A), keep it open, run again.")
    return tests[0]


def main(argv):
    try:
        names = companies()
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Tally is not answering on {URL}: {e}\n"
                 "Open TallyPrime and set F1 Help > Settings > Connectivity > Client/Server: Both, port 9000.")
    print(f"Tally on {URL} - companies open: {', '.join(names) or 'none'}")
    if not argv:
        return
    company = pick_company(names)
    print(f"Using company: {company}")
    if argv[0] == "create":
        result(post(envelope(company, "All Masters", masters_xml())), "ledgers / stock items")
        for no, d, party, po, lines, expect in invoices():
            xml, total = voucher_xml(no, d, party, po, lines)
            r = result(post(envelope(company, "Vouchers", xml)), f"{no} {d:%d-%m-%Y} {party[:28]:28} Rs {total:,.2f}")
            if r.get("CREATED"):
                print(f"      -> hub should show: {expect}")
        print("\nNow in the hub: GRIN & Payments > Get data > Pull from Tally, From 01-10-2026 to today.\n"
              "Expected log: 4 TAFE sales invoices (99005 is not a TAFE party).")
    elif argv[0] == "delete":
        for no, d, *_ in invoices():
            body = (f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER DATE="{d:%d-%b-%Y}" TAGNAME="Voucher Number" '
                    f'TAGVALUE="{no}" VCHTYPE="Sales" ACTION="Delete"><HASCASHFLOW>No</HASCASHFLOW></VOUCHER></TALLYMESSAGE>')
            result(post(envelope(company, "Vouchers", body)), f"delete {no}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
