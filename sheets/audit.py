"""Audit tab operations — ephemeral, cleared each run."""
from __future__ import annotations

import logging
import gspread

from config import AUDIT_HEADERS
from screening.stage1 import FilterResult
from sheets._retry import append_rows_with_retry

logger = logging.getLogger(__name__)


def clear_and_write_headers(ws: gspread.Worksheet) -> None:
    # NOTE (2026-09-26): ws.clear() sends an empty-body POST that this
    # network's proxy rejects with HTTP 411. batch_clear sends a JSON body
    # and goes through fine - same effect here.
    ws.batch_clear([f"A1:{gspread.utils.rowcol_to_a1(ws.row_count, ws.col_count)}"])
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
        append_rows_with_retry(ws, rows, value_input_option="USER_ENTERED")
        logger.info(f"Audit tab: wrote {len(rows)} rejections")
