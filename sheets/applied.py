"""Applied tab operations — persistent, grows over time."""
from __future__ import annotations

import logging
from datetime import date, timedelta

import gspread

from config import APPLIED_HEADERS
from models.job import ScreenedJob

logger = logging.getLogger(__name__)


def add_job(
    ws: gspread.Worksheet,
    job: ScreenedJob,
    resume_link: str,
    cover_letter_link: str,
    angle_used: str,
    notes: str = "",
    status: str = "Ready to Apply",
) -> None:
    today = date.today()
    followup = today + timedelta(days=7)

    row = [
        today.isoformat(),
        job.company,
        job.title,
        job.location,
        resume_link,
        cover_letter_link,
        job.url,
        angle_used,
        job.confidence,
        job.source,
        status,
        "",
        followup.isoformat(),
        "No",
        notes,
    ]
    # Use explicit row detection instead of append_row — gspread's append_row
    # misdetects the table bounds when the sheet has conditional formatting/banding
    # spanning many columns, causing each row to land 12 columns to the right.
    col_a = ws.col_values(1)  # 1-indexed; returns values up to last non-empty cell
    next_row = len(col_a) + 1
    ws.update(f"A{next_row}:O{next_row}", [row], value_input_option="USER_ENTERED")


def get_all_applied(ws: gspread.Worksheet) -> list[dict]:
    return ws.get_all_records()
