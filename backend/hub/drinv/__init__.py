"""DR -> Invoice module of the SDEW Hub (page /drinv/, routes /api/drinv/...).

Upload TAFE Delivery Request PDFs -> one draft sales invoice per DR line, filled the way the office fills
them in Tally today:
    rate      the PO price valid on the invoice date (gross + packing + freight) from the hub's PO data,
              which the PO master refreshes from TAFE Channel every day (8 am / 9 pm)
    GST       MDU (Tamil Nadu, same state)  -> CGST + SGST;  DBR (Karnataka) -> IGST
              rate from the sales ledger the part was last invoiced with (5 % for 8708 parts, 18 % for bolts
              73181500 and the breather 84099941); total rounded to the rupee with a Round Off line
    packing   packages = DR bins, pieces = DR unit size, total nos = qty
    remarks   FOR CRATE - <crate> - n NOS LID - <lid> - n NOS DR <dr>   (crate/lid as last invoiced)
Drafts are checked, edited and verified here, then sent to TallyPrime (GST SALES NEW) through the Tally
bridge; the IRN / e-way bill is generated in Tally as today.
"""
from ..http import ApiError, Request, Response, module_route  # noqa: F401

route = module_route("drinv")
