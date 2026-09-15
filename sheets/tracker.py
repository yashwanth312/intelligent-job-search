"""Tracker tab — applied job pipeline. Populated by sync_applied.py."""
from __future__ import annotations

import logging
from datetime import date, timedelta

import gspread

logger = logging.getLogger(__name__)


def add_job(
    ws: gspread.Worksheet,
    date_applied: str,
    company: str,
    title: str,
    location: str,
    apply_link: str,
    status: str = "",
    notes: str = "",
    confidence: int | str = "",
) -> None:
    followup = (date.fromisoformat(date_applied) + timedelta(days=7)).isoformat()

    row = [
        date_applied,   # Date Applied
        company,        # Company
        title,          # Job Title
        location,       # Location
        apply_link,     # Apply Link
        status,         # Status
        followup,       # Follow-up Date
        "No",           # Follow-up Sent
        notes,          # Notes
        confidence,     # Confidence
    ]
    # append_row (unlike update on an explicit range) auto-grows the sheet's
    # grid when needed, so it doesn't hit "exceeds grid limits" once the
    # tracker outgrows the tab's default row count.
    ws.append_row(row, value_input_option="USER_ENTERED")


def get_all(ws: gspread.Worksheet) -> list[dict]:
    return ws.get_all_records()


def get_existing_fingerprints(ws: gspread.Worksheet) -> set[str]:
    """Return a set of 'company||title' strings already in Tracker."""
    rows = ws.get_all_records()
    return {
        f"{r.get('Company', '').strip().lower()}||{r.get('Job Title', '').strip().lower()}"
        for r in rows
    }
