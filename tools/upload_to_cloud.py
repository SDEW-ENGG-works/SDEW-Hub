"""Copy the hub's data from this PC (data\\sdew_hub.db) up to the Turso cloud database used by the website.

    python tools\\upload_to_cloud.py --check   only show what is different, change nothing
    python tools\\upload_to_cloud.py           REPLACES every table in the cloud with this PC's rows

Needs TURSO_DATABASE_URL and TURSO_AUTH_TOKEN in .env (a NEW Turso database for the hub - not the old
CHEP or DQMS ones). Afterwards put USE_CLOUD_DB=1 in .env so the PC and the website share the same data.
"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from hub import config  # noqa: E402
from hub.db import migrate  # noqa: E402
from hub.turso import Connection  # noqa: E402

BATCH = 400


def main():
    env = config.read_env()
    url, token = env.get("TURSO_DATABASE_URL"), env.get("TURSO_AUTH_TOKEN")
    if not (url and token):
        sys.exit("Put TURSO_DATABASE_URL and TURSO_AUTH_TOKEN in .env first.")
    local = sqlite3.connect(config.DB_FILE)
    local.row_factory = sqlite3.Row
    cloud = Connection(url, token, timeout=180)
    migrate(cloud)
    tables = [r[0] for r in local.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    print(f"{'table':<20} {'this PC':>9} {'cloud':>9}")
    for t in tables:
        n_l = local.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        n_c = cloud.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
        print(f"{t:<20} {n_l:>9} {n_c:>9}")
    if "--check" in sys.argv:
        return
    if input("\nReplace the cloud data with this PC's data? (yes/no): ").strip().lower() not in ("y", "yes"):
        print("Nothing changed.")
        return
    for t in tables:
        cols = [r[1] for r in local.execute(f"PRAGMA table_info({t})")]
        cloud.execute(f"DELETE FROM {t}")
        cloud.commit()
        sql = f"INSERT INTO {t}({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})"
        rows = local.execute(f"SELECT {', '.join(cols)} FROM {t}").fetchall()
        for i in range(0, len(rows), BATCH):
            for r in rows[i:i + BATCH]:
                cloud.execute(sql, tuple(r))
            cloud.commit()
        print(f"  {t:<20} {len(rows):>7} rows")
    print("Done.")


if __name__ == "__main__":
    main()
