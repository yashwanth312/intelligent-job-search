"""Tests for the Sheets write retry helper."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


def test_succeeds_on_first_attempt():
    from sheets._retry import append_rows_with_retry
    ws = MagicMock()
    rows = [["a", "b"], ["c", "d"]]
    append_rows_with_retry(ws, rows)
    ws.append_rows.assert_called_once_with(rows, value_input_option="USER_ENTERED")


def test_retries_on_failure_then_succeeds():
    from sheets._retry import append_rows_with_retry
    ws = MagicMock()
    ws.append_rows.side_effect = [Exception("quota exceeded"), Exception("timeout"), None]
    with patch("sheets._retry.time.sleep"):
        append_rows_with_retry(ws, [["a"]], max_attempts=3)
    assert ws.append_rows.call_count == 3


def test_raises_after_max_attempts_exhausted():
    from sheets._retry import append_rows_with_retry
    ws = MagicMock()
    ws.append_rows.side_effect = Exception("permanent error")
    with patch("sheets._retry.time.sleep"), \
         pytest.raises(Exception, match="permanent error"):
        append_rows_with_retry(ws, [["a"]], max_attempts=3)
    assert ws.append_rows.call_count == 3


def test_logs_sqlite_message_after_max_attempts():
    from sheets._retry import append_rows_with_retry
    ws = MagicMock()
    ws.append_rows.side_effect = Exception("error")
    with patch("sheets._retry.time.sleep"), \
         patch("sheets._retry.logger") as mock_log, \
         pytest.raises(Exception):
        append_rows_with_retry(ws, [["a"]], max_attempts=2)
    mock_log.error.assert_called_once()
    assert "SQLite" in mock_log.error.call_args[0][0]


def test_passes_value_input_option():
    from sheets._retry import append_rows_with_retry
    ws = MagicMock()
    append_rows_with_retry(ws, [["a"]], value_input_option="RAW")
    ws.append_rows.assert_called_once_with([["a"]], value_input_option="RAW")
