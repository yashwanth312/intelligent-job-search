"""Rescreen jobs in the Daily sheet using Stage 2 Claude CLI.

  python rescreen.py                # rescreen every Daily row
  python rescreen.py --failed-only  # only rows whose Stage 2 call failed
                                    # ("Claude screening failed — not scored")
"""
from __future__ import annotations

import sys

from config import DB_FILE, DAILY_MIN_CONFIDENCE, SCREENING_BATCH_SIZE
from db.database import Database
from models.job import RawJob
from screening.stage2 import Stage2Screen, UNSCORED_PREFIX
from sheets.client import SheetsClient
from sheets import daily as daily_ops
from sheets._retry import append_rows_with_retry

FAILED_PREFIX = UNSCORED_PREFIX

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _row_to_raw_job(row: dict, db: Database) -> RawJob:
    company = row.get("Company", "")
    title = row.get("Job Title", "")
    location = row.get("Location", "")
    source = row.get("Source", "")
    url = row.get("Apply Link", "")
    fingerprint = f"{company.strip().lower()}||{title.strip().lower()}"

    db_record = db.get_job_by_fingerprint(fingerprint)
    description: str | None = None
    if db_record:
        description = db_record.get("description") or None

    return RawJob(
        title=title,
        company=company,
        location=location,
        description=description,
        url=url,
        source=source,
        salary_min=None,
        salary_max=None,
        posted_at=None,
    )


def main(failed_only: bool = False) -> None:
    print("Connecting to Google Sheets and SQLite...")
    sheets = SheetsClient()
    daily_ws = sheets.get_daily_sheet()
    db = Database(DB_FILE)
    db.initialize()

    try:
        print("Reading Daily tab...")
        rows = daily_ws.get_all_records()
        if not rows:
            print("Daily tab is empty — nothing to rescreen.")
            return

        kept_values: list[list] = []
        if failed_only:
            # Keep every non-failed row exactly as it is (incl. the user's
            # Status column) and rescreen only the Claude-failed defaults.
            all_values = daily_ws.get_all_values()[1:]
            failed_idx = [i for i, row in enumerate(rows)
                          if str(row.get("AI Reasoning", "")).startswith(FAILED_PREFIX)]
            if not failed_idx:
                print("No Claude-failed rows on the Daily tab — nothing to rescreen.")
                return
            kept_values = [v for i, v in enumerate(all_values) if i not in set(failed_idx)]
            rows = [rows[i] for i in failed_idx]
            print(f"{len(rows)} Claude-failed row(s); keeping {len(kept_values)} others untouched")

        print(f"Reconstructing {len(rows)} jobs from sheet + SQLite...")
        raw_jobs = [_row_to_raw_job(row, db) for row in rows]

        no_desc = sum(1 for j in raw_jobs if not j.description)
        if no_desc:
            print(
                f"  {no_desc} job(s) have no description in SQLite "
                "— will be screened without JD text"
            )

        stage2 = Stage2Screen(profile_path="profile.yaml")
        try:
            stage2.validate_cli()
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        num_batches = (len(raw_jobs) + SCREENING_BATCH_SIZE - 1) // SCREENING_BATCH_SIZE
        print(f"Running Stage 2 on {len(raw_jobs)} jobs ({num_batches} batch(es))...")
        screened = stage2.screen_batch(raw_jobs)

        daily_jobs = [j for j in screened if daily_ops.belongs_on_daily(j)]
        dropped_n = len(screened) - len(daily_jobs)

        still_failed = sum(1 for j in screened if j.confidence is None)
        if still_failed:
            print(f"  {still_failed} job(s) failed screening again (left unscored on Daily)")
        print(f"Rewriting Daily tab ({len(kept_values) + len(daily_jobs)} jobs)...")
        daily_ops.clear_and_write_headers(daily_ws)
        if kept_values:
            append_rows_with_retry(daily_ws, kept_values, value_input_option="USER_ENTERED")
        daily_ops.write_screened_jobs(daily_ws, daily_jobs)

        print(f"\nDone.  {len(daily_jobs)} on Daily  ·  {dropped_n} below "
              f"confidence {DAILY_MIN_CONFIDENCE} (dropped from sheet)")
    finally:
        db.close()


if __name__ == "__main__":
    main(failed_only="--failed-only" in sys.argv[1:])
