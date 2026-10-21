"""Write data/legacy_schema.md: every table and column in the copied app databases,
with a few sample rows. Share this file to write the migration into the unified tables."""
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import config, db  # noqa: E402


def main():
    out = ["# Legacy database structure\n"]
    for app in config.LEGACY_APPS:
        paths = db.legacy_db_paths(app)
        out.append(f"\n## {app['name']}\n")
        if not paths:
            out.append("_No database copied yet._\n")
        for path in paths:
            con = db.legacy_connect(path)
            out.append(f"\n### {path.relative_to(config.ROOT)}\n")
            for (name, sql) in con.execute("SELECT name, sql FROM sqlite_master "
                                           "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
                n = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                out.append(f"\n#### {name} ({n} rows)\n\n```sql\n{sql}\n```\n")
                sample = con.execute(f'SELECT * FROM "{name}" LIMIT 3').fetchall()
                for r in sample:
                    out.append("- " + " | ".join(str(v)[:40] for v in tuple(r)) + "\n")
            con.close()
    target = config.DATA / "legacy_schema.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(out), encoding="utf-8")
    print(f"Written: {target}")


if __name__ == "__main__":
    main()
