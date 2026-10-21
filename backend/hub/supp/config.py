"""Paths for this module inside the hub (same names the old app's config.py had)."""
import os

from ..config import (DATA_DIR, DB_FILE, ENV_FILE, ON_VERCEL, PROJECT_ROOT, cloud_db, db_mode,  # noqa: F401
                      read_env, upload_dir)
from .. import config as _hub

APP_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(_hub.FRONTEND_DIR, "supp")
UPLOAD_DIR = upload_dir("supp")
DEFAULT_TEMPLATE = os.path.join(APP_DIR, "templates", "BulkTransferTemplate.xlsx")
