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
