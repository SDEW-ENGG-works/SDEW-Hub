"""Paths and settings for the whole SDEW Hub (one app, one database, one .env)."""
import os

HUB_DIR = os.path.dirname(os.path.abspath(__file__))          # backend/hub
BACKEND_DIR = os.path.dirname(HUB_DIR)
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)                     # the SDEWHub folder

ON_VERCEL = bool(os.environ.get("VERCEL"))

FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
# On Vercel only /tmp can be written (and it is wiped) - everything lasting is in Turso.
DATA_DIR = os.environ.get("HUB_DATA_DIR") or ("/tmp/sdew-hub-data" if ON_VERCEL else os.path.join(PROJECT_ROOT, "data"))
DB_FILE = os.path.join(DATA_DIR, "sdew_hub.db")
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")
DEFAULT_PORT = 8050

MODULES = ("supp", "chep", "dqms", "grin")
os.makedirs(DATA_DIR, exist_ok=True)


def upload_dir(module):
    d = os.path.join(DATA_DIR, "uploads", module)
    os.makedirs(d, exist_ok=True)
    return d


ENV_KEYS = ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "APP_PASSWORD", "LEAP_USER", "LEAP_PASS",
            "TAFE_USER", "TAFE_PASS", "TAFE_URL", "USE_CLOUD_DB", "HUB_PORT",
            "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "MAIL_FROM", "SMTP_SSL")


def read_env():
    """Values from .env. Real environment variables win (Vercel)."""
    vals = {}
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    vals[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    for k in ENV_KEYS:
        if os.environ.get(k):
            vals[k] = os.environ[k]
    return vals


def cloud_db():
    """(url, token) when the hub should use the Turso cloud database:
    - on Vercel: from the environment variables;
    - on the PC: only when .env has USE_CLOUD_DB=1 (plus the two Turso keys).
    Otherwise the PC keeps its own data\\sdew_hub.db."""
    url, token = os.environ.get("TURSO_DATABASE_URL"), os.environ.get("TURSO_AUTH_TOKEN")
    if url and token:
        return url, token
    env = read_env()
    if str(env.get("USE_CLOUD_DB", "")).strip().lower() in ("1", "true", "yes", "on"):
        url, token = env.get("TURSO_DATABASE_URL"), env.get("TURSO_AUTH_TOKEN")
        if url and token:
            return url, token
    return None


def db_mode():
    return "cloud" if cloud_db() else "local"
