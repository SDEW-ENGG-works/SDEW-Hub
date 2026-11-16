"""Shows what the last Pull from Tally stored: groups, ledgers, ledger balances and stock values.
Reads the same database the hub uses (Turso when .env has USE_CLOUD_DB=1, else data/sdew_hub.db). Read only.

    python tools\\check_tally_books.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from hub import config  # noqa: E402
from hub.db import get_db, rows  # noqa: E402


def main():
    print("Database:", "Turso (cloud)" if config.cloud_db() else config.DB_FILE)
    get_db()   # creates the new tables if the hub has not started since the update
    for t in ("gp_tally_vouchers", "gp_tally_groups", "gp_tally_ledgers", "gp_tally_balances", "gp_tally_stock"):
        print(f"  {t:20} {rows(f'SELECT COUNT(*) n FROM {t}')[0]['n']:>8} rows")
    print("\nLast pulled:", rows("SELECT MAX(pulled_at) p FROM gp_tally_ledgers")[0]["p"] or "never")

    print("\nBalance dates (ledgers with a balance, debit total, credit total):")
    for r in rows("SELECT company, as_on, COUNT(*) n, "
                  "SUM(CASE WHEN CAST(balance AS REAL) > 0 THEN CAST(balance AS REAL) END) dr, "
                  "SUM(CASE WHEN CAST(balance AS REAL) < 0 THEN -CAST(balance AS REAL) END) cr "
                  "FROM gp_tally_balances GROUP BY company, as_on ORDER BY company, as_on"):
        print(f"  {r['company'] or '(open company)':20} {r['as_on']}  {r['n']:>5} ledgers  "
              f"Dr {r['dr'] or 0:>16,.2f}  Cr {r['cr'] or 0:>16,.2f}")

    print("\nStock value by date:")
    for r in rows("SELECT company, as_on, COUNT(*) n, SUM(CAST(value AS REAL)) v FROM gp_tally_stock "
                  "GROUP BY company, as_on ORDER BY company, as_on"):
        print(f"  {r['company'] or '(open company)':20} {r['as_on']}  {r['n']:>5} items  value {r['v'] or 0:>16,.2f}")

    print("\nTop-level groups and how many ledgers sit anywhere under them:")
    groups = {(g["company"], g["name"]): g["parent"] for g in rows("SELECT company, name, parent FROM gp_tally_groups")}

    def top(company, name):
        seen = set()
        while groups.get((company, name)) and name not in seen:
            seen.add(name)
            name = groups[(company, name)]
        return name
    counts = {}
    for le in rows("SELECT company, parent FROM gp_tally_ledgers"):
        k = (le["company"], top(le["company"], le["parent"]))
        counts[k] = counts.get(k, 0) + 1
    for (c, g), n in sorted(counts.items()):
        print(f"  {c or '(open company)':20} {g or '(no group)':30} {n:>5} ledgers")

    print("\nA few ledgers with their raw Tally text (to check the sign: Tally writes a debit as minus):")
    for r in rows("SELECT b.ledger, l.parent, b.as_on, b.balance, b.raw FROM gp_tally_balances b "
                  "JOIN gp_tally_ledgers l ON l.company = b.company AND l.name = b.ledger "
                  "WHERE b.as_on = (SELECT MAX(as_on) FROM gp_tally_balances) "
                  "ORDER BY ABS(CAST(b.balance AS REAL)) DESC LIMIT 8"):
        print(f"  {r['ledger'][:40]:40} {r['parent'][:22]:22} {r['balance']:>16}  (Tally: {r['raw']})")


if __name__ == "__main__":
    main()
