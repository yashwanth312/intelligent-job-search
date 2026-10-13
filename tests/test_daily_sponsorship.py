"""Tests for the Sponsorship column label derivation."""
from __future__ import annotations

from models.job import ScreenedJob
from sheets.daily import _sponsorship_label


def _screened(source: str, verified: bool | None) -> ScreenedJob:
    return ScreenedJob(
        title="Cloud Engineer",
        company="Acme",
        location="Remote",
        url="https://example.com/job",
        source=source,
        h1b_sponsor_verified=verified,
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


def test_unchecked_job_returns_unknown_for_every_source():
    # Board ATS jobs are checked like any other source since 2026-10-03, so
    # None only means the lookup errored or timed out — same label everywhere.
    for source in ("greenhouse-anthropic", "lever-stripe", "ashby-foo",
                   "hackernews", "remoteok", "linkedin"):
        job = _screened(source, None)
        assert _sponsorship_label(job) == "Unknown"


from unittest.mock import MagicMock

from sheets.daily import write_screened_jobs


def _ws_mock():
    """Minimal worksheet stand-in capturing append_rows calls."""
    ws = MagicMock()
    return ws


def test_write_screened_jobs_emits_16_columns_per_row():
    ws = _ws_mock()
    jobs = [_screened("linkedin", True), _screened("hackernews", False)]
    write_screened_jobs(ws, jobs)

    assert ws.append_rows.called
    rows = ws.append_rows.call_args[0][0]
    assert len(rows) == 2
    for row in rows:
        assert len(row) == 16, f"row has {len(row)} cells, expected 16"


def test_write_screened_jobs_status_at_index_4_blank():
    ws = _ws_mock()
    write_screened_jobs(ws, [_screened("linkedin", True)])
    row = ws.append_rows.call_args[0][0][0]
    # Status is user-filled; the row builder writes ""
    assert row[4] == ""


def test_write_screened_jobs_interview_score_at_index_5_blank_when_unset():
    ws = _ws_mock()
    write_screened_jobs(ws, [_screened("linkedin", True)])
    row = ws.append_rows.call_args[0][0][0]
    assert row[5] == ""


def test_write_screened_jobs_interview_score_at_index_5():
    ws = _ws_mock()
    job = _screened("linkedin", True)
    job.interview_likelihood = 42
    write_screened_jobs(ws, [job])
    row = ws.append_rows.call_args[0][0][0]
    assert row[5] == 42


def test_write_screened_jobs_risk_flags_at_index_6():
    ws = _ws_mock()
    job = _screened("linkedin", True)
    job.risk_flags = ["seniority_mismatch", "salary_below_floor"]
    write_screened_jobs(ws, [job])
    row = ws.append_rows.call_args[0][0][0]
    assert row[6] == "seniority_mismatch, salary_below_floor"


def test_write_screened_jobs_sponsorship_at_index_13():
    ws = _ws_mock()
    write_screened_jobs(ws, [_screened("linkedin", True)])
    row = ws.append_rows.call_args[0][0][0]
    assert row[13] == "Verified sponsor"


def test_write_screened_jobs_sponsorship_no_history():
    ws = _ws_mock()
    write_screened_jobs(ws, [_screened("hackernews", False)])
    row = ws.append_rows.call_args[0][0][0]
    assert row[13] == "No H-1B history"


def test_write_screened_jobs_sponsorship_curated_unknown():
    ws = _ws_mock()
    write_screened_jobs(ws, [_screened("greenhouse-anthropic", None)])
    row = ws.append_rows.call_args[0][0][0]
    assert row[13] == "Unknown"


def test_daily_cutoff_is_three_and_unscored_rows_stay_for_rescreen():
    from config import DAILY_MIN_CONFIDENCE
    from sheets.daily import belongs_on_daily
    assert DAILY_MIN_CONFIDENCE == 3
    assert belongs_on_daily(_screened("linkedin", True).model_copy(update={"confidence": 3}))
    assert not belongs_on_daily(_screened("linkedin", True).model_copy(update={"confidence": 2}))
    # Stage 2 failure: no score yet, kept so `rescreen.py --failed-only` finds it
    assert belongs_on_daily(_screened("linkedin", True).model_copy(update={"confidence": None}))


def test_unscored_row_has_blank_confidence_and_sorts_last():
    ws = _ws_mock()
    scored = _screened("linkedin", True)
    unscored = scored.model_copy(update={"confidence": None, "company": "Zed"})
    write_screened_jobs(ws, [unscored, scored])
    rows = ws.append_rows.call_args[0][0]
    assert rows[0][3] == 4
    assert rows[1][3] == ""
