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
    rows = []
    today = date.today().isoformat()

    for job in jobs:
        salary = ""
        if job.salary_min and job.salary_max:
            salary = f"${job.salary_min:,} - ${job.salary_max:,}"
        elif job.salary_min:
            salary = f"${job.salary_min:,}+"

        rows.append([
            today,
            job.company,
            job.title,
            job.location,
            job.source,
            job.confidence,
            job.reasoning,
            job.suggested_angle,
            ", ".join(job.risk_flags),
            ", ".join(job.match_signals),
            salary,
            job.url,
            "",
            "",
        ])

    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info(f"Daily tab: wrote {len(rows)} jobs")


def get_apply_jobs(ws: gspread.Worksheet) -> list[dict]:
    """Read Daily tab and return jobs where Status = 'Apply'."""
    all_rows = ws.get_all_records()
    return [row for row in all_rows if str(row.get("Status", "")).strip().lower() == "apply"]
