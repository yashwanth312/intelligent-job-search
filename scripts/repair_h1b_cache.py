"""Purge H-1B cache rows poisoned by the pre-2026-09-13 sponsor matcher.

The old matcher fed a lightly-normalized company string straight to
h1bdata.info's prefix search. Decorated job-board names ("Amazon Web Services
(AWS)", "NVIDIA AI", "Hakkoda, an IBM Company") matched no legal filer, were
cached as definitive non-sponsors for 30 days, and silently dropped every
posting from that employer. Roughly 11% of all H-1B rejections came from brand
variants of employers already verified as sponsors — AWS alone was 3,139
postings.

screening/h1b_checker.py now strips that decoration, walks a fallback query
ladder, and lets a decorated name inherit its parent brand's verdict. The
shorter negative TTL means bad rows expire on their own within a week; this
script clears them now instead.

Only NEGATIVE rows are touched. Confirmed sponsors are facts and are kept.

Two classes are removed:
  * re-keyed  — the row's key no longer matches what the current normalizer
                produces for its company_raw, so it can never be read again
  * inherits  — the company is a decorated variant of a confirmed sponsor and
                would now resolve to True

Run:  python scripts/repair_h1b_cache.py            (dry run — prints only)
      python scripts/repair_h1b_cache.py --apply    (actually deletes)
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from config import DB_FILE  # noqa: E402
from screening.h1b_checker import H1BChecker  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="delete the rows (default: dry run)")
    ap.add_argument("--db", default=DB_FILE)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT company_key, company_raw, verified FROM h1b_sponsor_cache"
    ).fetchall()
    checker = H1BChecker.__new__(H1BChecker)
    checker._verified_keys = {r["company_key"] for r in rows if r["verified"]}

    rekeyed: list[str] = []
    inherits: list[tuple[str, int]] = []

    counts = conn.execute(
        "SELECT company, COUNT(*) n FROM screening_audit "
        "WHERE stage = 'stage_h1b' GROUP BY company"
    ).fetchall()
    dropped_by_company = {
        H1BChecker._normalize(r["company"]): r["n"] for r in counts
    }

    for r in rows:
        if r["verified"]:
            continue
        key, raw = r["company_key"], r["company_raw"]
        if H1BChecker._normalize(raw) != key:
            rekeyed.append(key)
        elif checker._inherits_sponsor(key):
            inherits.append((key, dropped_by_company.get(key, 0)))

    total_neg = sum(1 for r in rows if not r["verified"])
    print()
    print("=" * 66)
    print("  H-1B CACHE REPAIR" + ("" if args.apply else "  (dry run)"))
    print("=" * 66)
    print(f"  cached companies        {len(rows):,}")
    print(f"  of which negative       {total_neg:,}")
    print()
    print(f"  re-keyed by new matcher {len(rekeyed):,}  (unreadable dead rows)")
    print(f"  now inherit a sponsor   {len(inherits):,}  (were wrongly dropped)")

    if inherits:
        print()
        print("  Top employers this un-blocks (postings previously dropped):")
        for key, n in sorted(inherits, key=lambda kv: -kv[1])[:15]:
            print(f"    {n:6,d}  {key}")

    doomed = set(rekeyed) | {k for k, _ in inherits}
    print()
    if not args.apply:
        print(f"  Would delete {len(doomed):,} negative rows. Re-run with --apply.")
        print("=" * 66)
        print()
        return

    conn.executemany(
        "DELETE FROM h1b_sponsor_cache WHERE company_key = ? AND verified = 0",
        [(k,) for k in doomed],
    )
    conn.commit()
    print(f"  Deleted {len(doomed):,} negative rows — they re-check on the next run.")
    print("=" * 66)
    print()


if __name__ == "__main__":
    main()
