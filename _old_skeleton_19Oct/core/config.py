"""Paths, .env loading and the list of existing apps the hub brings in."""
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LEGACY = ROOT / "legacy"
STATIC = ROOT / "static"


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()

PORT = int(os.environ.get("HUB_PORT", "8050"))
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
# Folder that holds the existing apps. Default: the folder SDEWHub sits in
# (C:\Users\abhin\Downloads\SDEW when SDEWHub is unzipped there).
SOURCE_ROOT = __import__("pathlib").Path(os.environ.get("SDEW_SOURCE", str(ROOT.parent)))

# The existing apps, copied into legacy/<folder> by tools/setup_from_existing.py.
LEGACY_APPS = [
    {"key": "supp", "name": "Supplementary Bill", "folder": "SupplementaryBill",
     "port": 8020, "dbs": ["data/supp_bill.db"]},
    {"key": "chep", "name": "CHEP Transfer", "folder": "CHEPTransfer",
     "port": 8030, "dbs": ["data/chep.db"]},
    {"key": "dqms", "name": "DQMS Upload", "folder": "DQMSUpload",
     "port": 8040, "dbs": ["data/dqms.db"]},
]
LEGACY_BY_KEY = {a["key"]: a for a in LEGACY_APPS}
