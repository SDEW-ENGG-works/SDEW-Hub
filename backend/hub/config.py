"""Paths and settings for the whole SDEW Hub (one app, one database, one .env)."""
import os

HUB_DIR = os.path.dirname(os.path.abspath(__file__))          # backend/hub
BACKEND_DIR = os.path.dirname(HUB_DIR)
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)                     # the SDEWHub folder

ON_VERCEL = bool(os.environ.get("VERCEL"))
# Inside the Vercel Sandbox that runs the LEAP upload this is a normal machine, not the website.
if os.environ.get("LEAP_SANDBOX"):
    ON_VERCEL = False

# All times the hub writes (uploaded at, fetched at, report time, mail sent ...) are India time.
# Vercel's servers run on UTC, which showed every time 5 h 30 min early. "IST-5:30" is a fixed offset,
# so it needs no time-zone files on the server. On the Windows PC the clock is already India time.
if ON_VERCEL or os.environ.get("HUB_FORCE_IST"):
    import time as _time
    os.environ["TZ"] = "IST-5:30"
    if hasattr(_time, "tzset"):
        _time.tzset()

FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
# On Vercel only /tmp can be written (and it is wiped) - everything lasting is in Turso.
DATA_DIR = os.environ.get("HUB_DATA_DIR") or ("/tmp/sdew-hub-data" if ON_VERCEL else os.path.join(PROJECT_ROOT, "data"))
DB_FILE = os.path.join(DATA_DIR, "sdew_hub.db")
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")
DEFAULT_PORT = 8050

MODULES = ("supp", "chep", "dqms", "grin", "pay")
os.makedirs(DATA_DIR, exist_ok=True)


def upload_dir(module):
    d = os.path.join(DATA_DIR, "uploads", module)
    os.makedirs(d, exist_ok=True)
    return d


ENV_KEYS = ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "APP_PASSWORD", "LEAP_USER", "LEAP_PASS",
            "TAFE_USER", "TAFE_PASS", "TAFE_URL", "USE_CLOUD_DB", "HUB_PORT",
            "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "MAIL_FROM", "SMTP_SSL",
            "CHEP_TURSO_DATABASE_URL", "CHEP_TURSO_AUTH_TOKEN", "DQMS_TURSO_DATABASE_URL", "DQMS_TURSO_AUTH_TOKEN",
            "LEAP_RUNNER")


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


def cloud_mode():
    """True on Vercel, or on the PC with USE_CLOUD_DB=1 in .env."""
    if ON_VERCEL:
        return True
    return str(read_env().get("USE_CLOUD_DB", "")).strip().lower() in ("1", "true", "yes", "on")


def module_cloud_db(module):
    """(url, token) of the CHEP / DQMS module's OWN Turso database - the databases of the old CHEP and DQMS
    websites, where their live data is - when the hub runs in cloud mode and
    CHEP_TURSO_DATABASE_URL / CHEP_TURSO_AUTH_TOKEN (or DQMS_...) are set. Otherwise None (hub database).
    On the PC without USE_CLOUD_DB=1 the .env copies of these keys are only used by tools/import_from_apps.py."""
    if module not in ("chep", "dqms") or not cloud_mode() or cloud_db():
        return None     # the hub's own (primary) database holds everything once TURSO_DATABASE_URL is set
    env = read_env()
    p = module.upper()
    url, token = env.get(f"{p}_TURSO_DATABASE_URL"), env.get(f"{p}_TURSO_AUTH_TOKEN")
    return (url, token) if url and token else None


def db_mode():
    return "cloud" if cloud_db() or module_cloud_db("chep") or module_cloud_db("dqms") else "local"
