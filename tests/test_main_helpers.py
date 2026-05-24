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


def _make_screened(title, company, confidence, verdict_str, reasoning="", risk_flags=None):
    from models.job import ScreenedJob, ScreeningVerdict
    return ScreenedJob(
        title=title, company=company, location="Remote",
        url=f"https://example.com/{company.lower()}",
        source="greenhouse-test",
        verdict=ScreeningVerdict(verdict_str),
        confidence=confidence,
        reasoning=reasoning,
        match_signals=[],
        risk_flags=risk_flags or [],
    )


def test_dedup_daily_jobs_removes_lower_confidence_duplicate():
    from main import _dedup_daily_jobs
    screened = _make_screened("Cloud Engineer", "Acme", confidence=4, verdict_str="APPLY")
    unscreened = _make_screened("Cloud Engineer", "Acme", confidence=1, verdict_str="MAYBE",
                                reasoning="No JD available", risk_flags=["no_description"])
    result = _dedup_daily_jobs([unscreened, screened])
    assert len(result) == 1
    assert result[0].confidence == 4


def test_dedup_daily_jobs_passthrough_unique_jobs():
    from main import _dedup_daily_jobs
    job_a = _make_screened("Cloud Engineer", "Acme", confidence=4, verdict_str="APPLY")
    job_b = _make_screened("DevOps Engineer", "Beta", confidence=3, verdict_str="MAYBE")
    result = _dedup_daily_jobs([job_a, job_b])
    assert len(result) == 2


def test_dedup_daily_jobs_empty_list():
    from main import _dedup_daily_jobs
    assert _dedup_daily_jobs([]) == []
