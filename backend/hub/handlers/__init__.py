"""Importing this package registers every API route of the hub and of its three modules.

  /api/login, /api/logout, /api/auth     shared login
  /api/hub/...                           Today, search, invoice trail, part / PO / DR pages, drop box
  /api/supp/...                          Supplementary Bill (old app's /api/... routes)
  /api/chep/...                          CHEP Transfer
  /api/dqms/...                          DQMS Upload
  /api/grin/...                          GRIN & Payments
"""
from . import hub, login  # noqa: F401
from ..supp import handlers as _supp  # noqa: F401
from ..chep import handlers as _chep  # noqa: F401
from ..dqms import handlers as _dqms  # noqa: F401
from ..grin import handlers as _grin  # noqa: F401
