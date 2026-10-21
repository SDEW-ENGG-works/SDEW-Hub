"""Copy the existing SDEW apps into SDEWHub/legacy/ without touching the originals.

    python tools/setup_from_existing.py            # first copy
    python tools/setup_from_existing.py --data     # refresh only the databases from the originals
    python tools/setup_from_existing.py --code     # re-copy code too (overwrites legacy/ copies)

Originals are only read: files are copied, and each SQLite database is copied with the
SQLite backup API from a read-only connection, so a copy taken while the old app is
running is still consistent.
"""
import pathlib
import shutil
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import config  # noqa: E402

SKIP = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".venv", "venv", "node_modules",
                              "*.db-journal", "*.db-wal", "*.db-shm", "stale-*")


def copy_db(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    s = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
    d = sqlite3.connect(str(tmp))
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()
    tmp.replace(dst)


def main():
    args = set(sys.argv[1:])
    data_only = "--data" in args
    recopy_code = "--code" in args
    print(f"Reading existing apps from: {config.SOURCE_ROOT}")
    print(f"Copying into:               {config.LEGACY}\n")
    config.LEGACY.mkdir(parents=True, exist_ok=True)

    for app in config.LEGACY_APPS:
        src = config.SOURCE_ROOT / app["folder"]
        dst = config.LEGACY / app["folder"]
        if not src.exists():
            print(f"[skip] {app['name']}: {src} not found")
            continue
        if src.resolve() == dst.resolve() or config.ROOT.resolve() in src.resolve().parents:
            print(f"[skip] {app['name']}: source is inside SDEWHub")
            continue

        if not data_only:
            if dst.exists() and recopy_code:
                shutil.rmtree(dst)
            if not dst.exists():
                shutil.copytree(src, dst, ignore=SKIP)
                print(f"[code] {app['name']}: copied")
            else:
                print(f"[code] {app['name']}: already copied (use --code to re-copy)")

        for rel in [p.relative_to(src) for p in src.rglob("*.db")]:
            if any(part in (".git", "_old") for part in rel.parts):
                continue
            try:
                copy_db(src / rel, dst / rel)
                print(f"[data] {app['name']}: {rel}")
            except sqlite3.Error as e:
                print(f"[warn] {app['name']}: could not copy {rel}: {e}")

    print("\nDone. The original folders were not changed.")
    print("Next: python tools/inspect_legacy_dbs.py   then   start.bat")


if __name__ == "__main__":
    main()
