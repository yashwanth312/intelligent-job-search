"""Tests for the Sponsorship column label derivation."""
from __future__ import annotations

from models.job import ScreenedJob, ScreeningVerdict
from sheets.daily import _sponsorship_label


def _screened(source: str, verified: bool | None) -> ScreenedJob:
    return ScreenedJob(
        title="Cloud Engineer",
        company="Acme",
        location="Remote",
        url="https://example.com/job",
        source=source,
        h1b_sponsor_verified=verified,
        verdict=ScreeningVerdict.APPLY,
        confidence=4,
        reasoning="ok",
    )


def test_verified_true_returns_verified_sponsor():
    job = _screened("linkedin", True)
    assert _sponsorship_label(job) == "Verified sponsor"


def test_verified_false_returns_no_history():
    # Only kept jobs (HN/RemoteOK/curated) reach this with False
    job = _screened("hackernews", False)
    assert _sponsorship_label(job) == "No H-1B history"


def test_curated_source_with_none_returns_curated_unknown():
    for source in ("greenhouse-anthropic", "lever-stripe", "ashby-foo"):
        job = _screened(source, None)
        assert _sponsorship_label(job) == "Curated — unknown"


def test_non_curated_source_with_none_returns_blank():
    job = _screened("hackernews", None)
    assert _sponsorship_label(job) == ""


def test_non_curated_unknown_source_with_none_returns_blank():
    job = _screened("remoteok", None)
    assert _sponsorship_label(job) == ""


from unittest.mock import MagicMock

from sheets.daily import write_screened_jobs


def _ws_mock():
    """Minimal worksheet stand-in capturing append_rows calls."""
    ws = MagicMock()
    return ws


def test_write_screened_jobs_emits_15_columns_per_row():
    ws = _ws_mock()
    jobs = [_screened("linkedin", True), _screened("hackernews", False)]
    write_screened_jobs(ws, jobs)

    assert ws.append_rows.called
    rows = ws.append_rows.call_args[0][0]
    assert len(rows) == 2
    for row in rows:
        assert len(row) == 15, f"row has {len(row)} cells, expected 15"


def test_write_screened_jobs_status_at_index_4_blank():
    ws = _ws_mock()
    write_screened_jobs(ws, [_screened("linkedin", True)])
    row = ws.append_rows.call_args[0][0][0]
    # Status is user-filled; the row builder writes ""
    assert row[4] == ""


def test_write_screened_jobs_risk_flags_at_index_5():
    ws = _ws_mock()
    job = _screened("linkedin", True)
    job.risk_flags = ["seniority_mismatch", "salary_below_floor"]
    write_screened_jobs(ws, [job])
    row = ws.append_rows.call_args[0][0][0]
    assert row[5] == "seniority_mismatch, salary_below_floor"


def test_write_screened_jobs_sponsorship_at_index_12():
    ws = _ws_mock()
    write_screened_jobs(ws, [_screened("linkedin", True)])
    row = ws.append_rows.call_args[0][0][0]
    assert row[12] == "Verified sponsor"


def test_write_screened_jobs_sponsorship_no_history():
    ws = _ws_mock()
    write_screened_jobs(ws, [_screened("hackernews", False)])
    row = ws.append_rows.call_args[0][0][0]
    assert row[12] == "No H-1B history"


def test_write_screened_jobs_sponsorship_curated_unknown():
    ws = _ws_mock()
    write_screened_jobs(ws, [_screened("greenhouse-anthropic", None)])
    row = ws.append_rows.call_args[0][0][0]
    assert row[12] == "Curated — unknown"
