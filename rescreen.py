"""Rescreen all jobs in the Daily sheet using Stage 2 Claude CLI."""
from __future__ import annotations

import sys

from config import DB_FILE, SCREENING_BATCH_SIZE
from db.database import Database
from models.job import RawJob, ScreeningVerdict
from screening.stage2 import Stage2Screen
from sheets.client import SheetsClient
from sheets import daily as daily_ops

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


def main() -> None:
    print("Connecting to Google Sheets and SQLite...")
    sheets = SheetsClient()
    daily_ws = sheets.get_daily_sheet()
    db = Database(DB_FILE)
    db.initialize()

    print("Reading Daily tab...")
    rows = daily_ws.get_all_records()
    if not rows:
        print("Daily tab is empty — nothing to rescreen.")
        db.close()
        return

    print(f"Reconstructing {len(rows)} jobs from sheet + SQLite...")
    raw_jobs = [_row_to_raw_job(row, db) for row in rows]

    no_desc = sum(1 for j in raw_jobs if not j.description)
    if no_desc:
        print(
            f"  {no_desc} job(s) have no description in SQLite "
            "— will be screened without JD text"
        )

    stage2 = Stage2Screen(profile_path="profile.yaml")
    stage2.validate_cli()

    num_batches = (len(raw_jobs) + SCREENING_BATCH_SIZE - 1) // SCREENING_BATCH_SIZE
    print(f"Running Stage 2 on {len(raw_jobs)} jobs ({num_batches} batch(es))...")
    screened = stage2.screen_batch(raw_jobs)

    apply_n = sum(1 for j in screened if j.verdict == ScreeningVerdict.APPLY)
    maybe_n = sum(1 for j in screened if j.verdict == ScreeningVerdict.MAYBE)
    skip_n = sum(1 for j in screened if j.verdict == ScreeningVerdict.SKIP)

    daily_jobs = [
        j for j in screened
        if j.verdict in (ScreeningVerdict.APPLY, ScreeningVerdict.MAYBE)
    ]

    print(f"Rewriting Daily tab ({len(daily_jobs)} jobs)...")
    daily_ops.clear_and_write_headers(daily_ws)
    daily_ops.write_screened_jobs(daily_ws, daily_jobs)

    print(f"\nDone.  APPLY {apply_n}  ·  MAYBE {maybe_n}  ·  SKIP {skip_n} (dropped from sheet)")
    db.close()


if __name__ == "__main__":
    main()
