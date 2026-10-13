"""Tests for helper functions extracted from main.py."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


async def _never_returns(*args, **kwargs):
    """Coroutine that never completes — simulates a hung H1B checker."""
    await asyncio.sleep(9999)


@pytest.mark.asyncio
async def test_h1b_timeout_continues_without_raising():
    """When H1B checker hangs, the helper catches TimeoutError and returns normally."""
    from main import _h1b_check_with_timeout
    checker = MagicMock()
    checker.check_batch = _never_returns
    # timeout=0.01s ensures it fires immediately; must not raise
    await _h1b_check_with_timeout(checker, [], timeout=0.01)


@pytest.mark.asyncio
async def test_h1b_timeout_calls_checker_normally_when_fast():
    """When H1B checker completes quickly, it is called exactly once."""
    from main import _h1b_check_with_timeout
    checker = MagicMock()
    checker.check_batch = AsyncMock()
    await _h1b_check_with_timeout(checker, [], timeout=5)
    checker.check_batch.assert_called_once_with([])


def _make_screened(title, company, confidence, reasoning="", risk_flags=None):
    from models.job import ScreenedJob
    return ScreenedJob(
        title=title, company=company, location="Remote",
        url=f"https://example.com/{company.lower()}",
        source="greenhouse-test",
        confidence=confidence,
        reasoning=reasoning,
        match_signals=[],
        risk_flags=risk_flags or [],
    )


def test_dedup_daily_jobs_removes_lower_confidence_duplicate():
    from main import _dedup_daily_jobs
    screened = _make_screened("Cloud Engineer", "Acme", confidence=4)
    unscreened = _make_screened("Cloud Engineer", "Acme", confidence=None,
                                reasoning="No JD available", risk_flags=["no_description"])
    result = _dedup_daily_jobs([unscreened, screened])
    assert len(result) == 1
    assert result[0].confidence == 4


def test_dedup_daily_jobs_passthrough_unique_jobs():
    from main import _dedup_daily_jobs
    job_a = _make_screened("Cloud Engineer", "Acme", confidence=4)
    job_b = _make_screened("DevOps Engineer", "Beta", confidence=3)
    result = _dedup_daily_jobs([job_a, job_b])
    assert len(result) == 2


def test_dedup_daily_jobs_empty_list():
    from main import _dedup_daily_jobs
    assert _dedup_daily_jobs([]) == []


def test_audit_outcome_routes_on_confidence_cutoff():
    from main import _audit_outcome
    assert _audit_outcome(_make_screened("Cloud Engineer", "A", confidence=4)) == "DAILY"
    assert _audit_outcome(_make_screened("Cloud Engineer", "B", confidence=3)) == "DAILY"
    assert _audit_outcome(_make_screened("Cloud Engineer", "C", confidence=2)) == "REJECT"
    assert _audit_outcome(_make_screened("Cloud Engineer", "D", confidence=None)) == "UNSCORED"


def test_score_breakdown_counts_each_confidence_and_unscored():
    from main import _score_breakdown
    jobs = [_make_screened("Cloud Engineer", c, confidence=v)
            for c, v in (("A", 5), ("B", 3), ("C", 3), ("D", None))]
    out = _score_breakdown(jobs)
    assert "5: 1" in out and "3: 2" in out and "1: 0" in out and "unscored: 1" in out


def test_h1b_index_note_names_size_and_build_date():
    from datetime import date
    from main import _h1b_index_note
    from screening.lca_index import LcaIndex
    index = LcaIndex({"microsoft", "ibm"}, built="2026-10-09")
    assert _h1b_index_note(index, date(2026, 10, 9)) == "index 2 employers, built 2026-10-09"


def test_h1b_index_note_flags_a_stale_index():
    from datetime import date
    from main import _h1b_index_note
    from screening.lca_index import LcaIndex
    index = LcaIndex({"microsoft"}, built="2026-01-02")
    assert _h1b_index_note(index, date(2026, 10, 9)).endswith(
        "STALE: rebuild with scripts/build_lca_index.py")


def test_h1b_index_note_warns_when_there_is_no_index():
    from datetime import date
    from main import _h1b_index_note
    assert _h1b_index_note(None, date(2026, 10, 9)) == "NO INDEX: nothing dropped"
