"""Materials tab — generated resumes/CLs queue. Persistent, newest row at top."""
from __future__ import annotations

import logging
from datetime import date

import gspread

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
    today = date.today().isoformat()

    row = [
        today,              # Date Generated
        job.company,        # Company
        job.title,          # Job Title
        job.location,       # Location
        resume_link,        # Resume Link
        cover_letter_link,  # Cover Letter Link
        job.url,            # Apply Link
        angle_used,         # Angle Used
        job.confidence,     # Screen Confidence
        job.source,         # Source
        status,             # Status
        notes,              # Notes
    ]
    # Insert at row 2 (below the frozen header) so the newest job is always
    # at the top. insert_row shifts all existing rows down by one.
    ws.insert_row(row, index=2, value_input_option="USER_ENTERED")


def get_apply_ready_jobs(ws: gspread.Worksheet) -> list[dict]:
    """Return rows where Status = 'Ready to Apply' (jobs awaiting generation)."""
    all_rows = ws.get_all_records()
    return [r for r in all_rows if str(r.get("Status", "")).strip() == "Ready to Apply"]


def get_applied_jobs(ws: gspread.Worksheet) -> list[dict]:
    """Return rows where Status = 'Applied' — ready to sync to Tracker."""
    all_rows = ws.get_all_records()
    return [r for r in all_rows if str(r.get("Status", "")).strip() == "Applied"]


def get_generated_fingerprints(ws: gspread.Worksheet) -> set[str]:
    """Return company||title fingerprints for jobs with status 'Ready to Apply'.

    Only blocks re-generation of jobs still sitting in the queue — won't prevent
    a new opening at the same company/title from being processed months later.
    """
    all_rows = ws.get_all_records()
    return {
        f"{str(r.get('Company', '')).strip().lower()}||{str(r.get('Job Title', '')).strip().lower()}"
        for r in all_rows
        if str(r.get("Status", "")).strip() == "Ready to Apply"
    }
