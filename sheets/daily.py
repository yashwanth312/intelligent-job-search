"""Daily tab operations — ephemeral, cleared each run."""
from __future__ import annotations

import logging
from datetime import date

import gspread

from config import DAILY_HEADERS
from models.job import ScreenedJob

logger = logging.getLogger(__name__)


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

        rows.append([
            job.company,                          # Company
            job.title,                            # Job Title
            job.location,                         # Location
            job.confidence,                       # Confidence
            "",                                   # Status (user fills — right next to Confidence)
            job.source,                           # Source
            job.reasoning,                        # AI Reasoning
            job.suggested_angle,                  # Suggested Angle
            ", ".join(job.match_signals),         # Match Signals
            ", ".join(job.risk_flags),            # Risk Flags
            salary,                               # Salary Range
            job.url,                              # Apply Link
            "",                                   # Notes
        ])

    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info(f"Daily tab: wrote {len(rows)} jobs (sorted by confidence desc)")


def get_apply_jobs(ws: gspread.Worksheet) -> list[dict]:
    """Read Daily tab and return jobs where Status = 'Apply'."""
    all_rows = ws.get_all_records()
    return [row for row in all_rows if str(row.get("Status", "")).strip().lower() == "apply"]
