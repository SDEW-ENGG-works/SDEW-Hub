"""pay module of the SDEW Hub (was the separate Payment Marking app, moved in on 22-Oct-2026).

  Payment marking  TAFE payment export -> payment voucher no + date in the invoice register
  Sales marking    TAFE GRIN lines     -> GRN NO / GRN DATE / GRN QTY in 'TAFE SALES DETAILS'
Routes live under /api/pay/..., the page under /pay/. Tables start with pm_ (payment) and ps_ (sales).
"""
from ..http import ApiError, Request, Response, module_route  # noqa: F401

route = module_route("pay")
