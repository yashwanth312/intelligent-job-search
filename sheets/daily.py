"""Daily tab operations — ephemeral, cleared each run."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import gspread

from config import DAILY_HEADERS, DAILY_MIN_CONFIDENCE
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
    None  → "Unknown" (lookup errored or was still in flight at the timeout)
    """
    if job.h1b_sponsor_verified is True:
        return "Verified sponsor"
    if job.h1b_sponsor_verified is False:
        return "No H-1B history"
    return "Unknown"


def belongs_on_daily(job: ScreenedJob) -> bool:
    """Scored at or above config.DAILY_MIN_CONFIDENCE, or not scored at all.

    Unscored jobs (Stage 2 failed, or no description) carry no confidence to
    compare; they stay on Daily with a blank Confidence cell so
    `rescreen.py --failed-only` can find and score them."""
    return job.confidence is None or job.confidence >= DAILY_MIN_CONFIDENCE


def clear_and_write_headers(ws: gspread.Worksheet) -> None:
    # NOTE (2026-09-26): ws.clear() sends an empty-body POST that this
    # network's proxy rejects with HTTP 411. batch_clear sends a JSON body
    # and goes through fine - same effect here.
    ws.batch_clear([f"A1:{gspread.utils.rowcol_to_a1(ws.row_count, ws.col_count)}"])
    ws.append_row(DAILY_HEADERS)


def write_screened_jobs(ws: gspread.Worksheet, jobs: list[ScreenedJob]) -> None:
    # Best matches at the top; unscored rows (confidence None) at the bottom
    sorted_jobs = sorted(
        jobs,
        key=lambda j: (j.confidence or 0, j.interview_likelihood or 0),
        reverse=True,
    )

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
            job.confidence if job.confidence is not None else "",  # 3  Confidence
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
