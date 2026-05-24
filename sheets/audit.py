"""Audit tab operations — ephemeral, cleared each run."""
from __future__ import annotations

import logging
import gspread

from config import AUDIT_HEADERS
from screening.stage1 import FilterResult

logger = logging.getLogger(__name__)


def clear_and_write_headers(ws: gspread.Worksheet) -> None:
    ws.clear()
    ws.append_row(AUDIT_HEADERS)


def write_rejections(ws: gspread.Worksheet, rejections: list[FilterResult]) -> None:
    rows = []
    for r in rejections:
        rows.append([
            r.job.company,
            r.job.title,
            r.stage,
            r.reason,
            r.job.source,
            r.job.url,
        ])

    if rows:
        from sheets._retry import append_rows_with_retry
        append_rows_with_retry(ws, rows, value_input_option="USER_ENTERED")
        logger.info(f"Audit tab: wrote {len(rows)} rejections")
