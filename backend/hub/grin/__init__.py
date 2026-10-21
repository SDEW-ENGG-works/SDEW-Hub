"""grin module of the SDEW Hub: GRIN & Payment status of every TAFE invoice.

  Tally invoices  ->  GRINed on TAFE Channel?  ->  paid by TAFE?
                          no  -> reminder mail to the plant's buyer
Routes live under /api/grin/..., the page under /grin/.
"""
from ..http import ApiError, Request, Response, module_route  # noqa: F401

route = module_route("grin")
