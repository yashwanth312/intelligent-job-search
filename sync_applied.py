"""
============================================================
  SYNC APPLIED — Materials → Tracker
============================================================
  Reads the Materials tab for rows where Status = "Applied",
  deduplicates against the Tracker tab, and appends new rows
  to Tracker. Run this any time after you mark jobs Applied
  in the Materials sheet.

  Usage:
      python sync_applied.py
============================================================
"""
from __future__ import annotations

import logging
import sys
import time

from sheets.client import SheetsClient
from sheets import materials as materials_ops, tracker as tracker_ops
from sheets.formatting import format_tracker

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BAR = "─" * 60


def main() -> None:
    t0 = time.perf_counter()
    print()
    print("=" * 60)
    print("  SYNC APPLIED — Materials → Tracker")
    print("=" * 60)

    sheets = SheetsClient()
    materials_ws = sheets.get_materials_sheet()
    tracker_ws = sheets.get_tracker_sheet()

    applied_rows = materials_ops.get_applied_jobs(materials_ws)
    if not applied_rows:
        print("\n  No rows marked 'Applied' in Materials tab. Nothing to sync.\n")
        return

    print(f"\n  Found {len(applied_rows)} Applied row(s) in Materials.\n")

    existing = tracker_ops.get_existing_fingerprints(tracker_ws)
    synced = 0
    skipped = 0

    for row in applied_rows:
        company = str(row.get("Company", "")).strip()
        title = str(row.get("Job Title", "")).strip()
        fp = f"{company.lower()}||{title.lower()}"

        if fp in existing:
            print(f"  ── SKIP (already in Tracker): {company} | {title}")
            skipped += 1
            continue

        date_generated = str(row.get("Date Generated", "")).strip()
        location = str(row.get("Location", "")).strip()
        apply_link = str(row.get("Apply Link", "")).strip()

        tracker_ops.add_job(
            tracker_ws,
            date_applied=date_generated or time.strftime("%Y-%m-%d"),
            company=company,
            title=title,
            location=location,
            apply_link=apply_link,
        )
        existing.add(fp)
        synced += 1
        print(f"  ++ SYNCED: {company} | {title}")

    # Apply/refresh Tracker formatting after adding rows
    try:
        format_tracker(sheets.spreadsheet, tracker_ws)
    except Exception as e:
        logger.warning(f"Tracker formatting failed (data is fine): {e}")

    elapsed = time.perf_counter() - t0
    print()
    print("=" * 60)
    print(f"  Synced:  {synced} new row(s) added to Tracker")
    if skipped:
        print(f"  Skipped: {skipped} already in Tracker")
    print(f"  Time:    {elapsed:.1f}s")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
