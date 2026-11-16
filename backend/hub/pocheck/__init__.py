"""PO Price Check module of the SDEW Hub (page /pocheck/, routes /api/pocheck/...).

Two checks on files you upload:
  1. Excel verifier        TAFE's price-change Excel (RM working: Existing / Revised Basic price, Price Effective
                           Date per part) against the NEW PO .htm files (FinalPriceChange): is the revised price
                           in the PO, with the same rate and date?
  2. PO price changes      the OLD PO .htm against the NEW PO .htm, part by part: old rate, new rate, from when,
                           change in Rs and %. A PO with no old .htm uploaded is compared with the hub's own PO
                           data (what the Supplementary Bill and DQMS use).
"""
from ..http import ApiError, Request, Response, module_route  # noqa: F401

route = module_route("pocheck")
