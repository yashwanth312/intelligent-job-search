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
        "Ready to Apply",
        "",
        followup.isoformat(),
        "No",
        "",
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")


def get_all_applied(ws: gspread.Worksheet) -> list[dict]:
    return ws.get_all_records()
