"""Retry helper for gspread append_rows calls."""
from __future__ import annotations

import logging
import time

import gspread

logger = logging.getLogger(__name__)


def append_rows_with_retry(
    ws: gspread.Worksheet,
    rows: list[list],
    value_input_option: str = "USER_ENTERED",
    max_attempts: int = 3,
    backoff_base: float = 2.0,
) -> None:
    """Call ws.append_rows with exponential backoff retry.

    On final failure, logs a clear error that results are safely in SQLite,
    then re-raises so the caller is aware.
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            ws.append_rows(rows, value_input_option=value_input_option)
            return
        except Exception as e:
            last_exc = e
            if attempt < max_attempts - 1:
                wait = backoff_base ** attempt
                logger.warning(
                    f"Sheets write attempt {attempt + 1}/{max_attempts} failed: {e}"
                    f" — retrying in {wait:.0f}s"
                )
                time.sleep(wait)
    logger.error(
        f"Google Sheets write failed after {max_attempts} attempts — "
        "results are in SQLite but not visible in Sheets"
    )
    raise last_exc
