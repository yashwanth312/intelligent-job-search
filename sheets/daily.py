"""Daily tab operations — ephemeral, cleared each run."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import gspread

from config import DAILY_HEADERS
from models.job import ScreenedJob
from sheets._retry import append_rows_with_retry

logger = logging.getLogger(__name__)


def _humanize_posted(dt: datetime | None) -> str:
    """Render posted_at as 'Xm ago' / 'Xh ago' / 'Xd ago' — empty if unknown."""
    if dt is None:
        return ""
    now = datetime.now(timezone.utc)
    # Normalize naive datetimes to UTC so subtraction doesn't raise.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    days = seconds // 86400
    return f"{days}d ago"


def _sponsorship_label(job: ScreenedJob) -> str:
    """Render the Sponsorship column for a screened job.

    True  → "Verified sponsor" (LCA filings found on h1bdata.info)
    False → "No H-1B history" (only reaches Daily for kept-bucket sources)
    None  + curated ATS source → "Curated — unknown"
    None  + other source → "" (blank)
    """
    if job.h1b_sponsor_verified is True:
        return "Verified sponsor"
    if job.h1b_sponsor_verified is False:
        return "No H-1B history"
    if job.source.startswith(("greenhouse-", "lever-", "ashby-")):
        return "Curated — unknown"
    return ""


def clear_and_write_headers(ws: gspread.Worksheet) -> None:
    ws.clear()
    ws.append_row(DAILY_HEADERS)


def write_screened_jobs(ws: gspread.Worksheet, jobs: list[ScreenedJob]) -> None:
    # Sort by confidence descending so best matches are at the top
    sorted_jobs = sorted(jobs, key=lambda j: j.confidence, reverse=True)

    rows = []
    for job in sorted_jobs:
        salary = ""
        if job.salary_min and job.salary_max:
            salary = f"${job.salary_min:,} - ${job.salary_max:,}"
        elif job.salary_min:
            salary = f"${job.salary_min:,}+"

        interview_score = (
            job.interview_likelihood if job.interview_likelihood is not None else ""
        )

        rows.append([
            job.company,                          # 0  Company
            job.title,                            # 1  Job Title
            job.location,                         # 2  Location
            job.confidence,                       # 3  Confidence
            "",                                   # 4  Status (user fills)
            interview_score,                      # 5  Interview Score
            ", ".join(job.risk_flags),            # 6  Risk Flags
            job.url,                              # 7  Apply Link
            _humanize_posted(job.posted_at),      # 8  Posted (e.g. "3h ago")
            job.source,                           # 9  Source
            job.reasoning,                        # 10 AI Reasoning
            job.suggested_angle,                  # 11 Suggested Angle
            ", ".join(job.match_signals),         # 12 Match Signals
            _sponsorship_label(job),              # 13 Sponsorship
            salary,                               # 14 Salary Range
            "",                                   # 15 Notes
        ])

    if rows:
        append_rows_with_retry(ws, rows, value_input_option="USER_ENTERED")
        logger.info(f"Daily tab: wrote {len(rows)} jobs (sorted by confidence desc)")


def get_apply_jobs(ws: gspread.Worksheet) -> list[dict]:
    """Read Daily tab and return jobs where Status = 'Apply'."""
    all_rows = ws.get_all_records()
    return [row for row in all_rows if str(row.get("Status", "")).strip().lower() == "apply"]
