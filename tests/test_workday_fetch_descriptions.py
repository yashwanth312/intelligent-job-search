"""Tests for the Workday post-Stage-1 description fetch.

Covers the URL-parsing helper, JSON description extraction, and the bulk
fetch_descriptions() entrypoint with mocked aiohttp.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from models.job import RawJob
from sources.workday import (
    _build_detail_url,
    _extract_description,
    fetch_descriptions,
)


# ── URL parsing ──────────────────────────────────────────────────────────
class TestBuildDetailUrl:
    def test_basic_url(self):
        public = "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/Cloud-Engineer_JR123"
        result = _build_detail_url(public)
        assert result == (
            "https://nvidia.wd5.myworkdayjobs.com"
            "/wday/cxs/nvidia/NVIDIAExternalCareerSite/job/Cloud-Engineer_JR123"
        )

    def test_url_without_locale(self):
        public = "https://salesforce.wd12.myworkdayjobs.com/External_Career_Site/job/SF/SWE_JR1"
        result = _build_detail_url(public)
        assert result == (
            "https://salesforce.wd12.myworkdayjobs.com"
            "/wday/cxs/salesforce/External_Career_Site/job/SF/SWE_JR1"
        )

    def test_non_workday_returns_none(self):
        assert _build_detail_url("https://linkedin.com/jobs/view/123") is None

    def test_empty_returns_none(self):
        assert _build_detail_url("") is None


# ── Description extraction ───────────────────────────────────────────────
class TestExtractDescription:
    def test_strips_html_returns_text(self):
        payload = {
            "jobPostingInfo": {
                "jobDescription": (
                    "<p>We are hiring a Cloud Engineer.</p>"
                    "<p>Requirements: AWS, Kubernetes, Terraform.</p>"
                )
            }
        }
        text = _extract_description(payload)
        assert text is not None
        assert "Cloud Engineer" in text
        assert "AWS" in text
        assert "<p>" not in text

    def test_returns_none_on_missing_field(self):
        assert _extract_description({}) is None
        assert _extract_description({"jobPostingInfo": {}}) is None
        assert _extract_description({"jobPostingInfo": {"jobDescription": ""}}) is None

    def test_returns_none_on_too_short(self):
        payload = {"jobPostingInfo": {"jobDescription": "<p>Short.</p>"}}
        assert _extract_description(payload) is None

    def test_handles_none_payload(self):
        assert _extract_description(None) is None


# ── Bulk fetch_descriptions() ────────────────────────────────────────────
def _wd_job(**kwargs) -> RawJob:
    defaults = {
        "title": "Cloud Engineer",
        "company": "NVIDIA",
        "location": "Santa Clara, CA",
        "description": None,
        "url": "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/CE_JR1",
        "source": "workday-nvidia",
    }
    defaults.update(kwargs)
    return RawJob(**defaults)


def _mock_session(json_payload: dict, status: int = 200):
    """Return an AsyncMock aiohttp.ClientSession that yields the given JSON
    on every GET. Patch into sources.workday.aiohttp.ClientSession.
    """
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_payload)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


class TestFetchDescriptions:
    @pytest.mark.asyncio
    async def test_skips_jobs_with_existing_description(self):
        jobs = [_wd_job(description="Already filled")]
        n = await fetch_descriptions(jobs)
        assert n == 0
        assert jobs[0].description == "Already filled"

    @pytest.mark.asyncio
    async def test_skips_non_workday_sources(self):
        jobs = [_wd_job(source="linkedin")]
        n = await fetch_descriptions(jobs)
        assert n == 0

    @pytest.mark.asyncio
    async def test_empty_input_returns_zero(self):
        assert await fetch_descriptions([]) == 0

    @pytest.mark.asyncio
    async def test_fills_description_on_200(self):
        jobs = [_wd_job()]
        payload = {
            "jobPostingInfo": {
                "jobDescription": (
                    "<p>Cloud Engineer at NVIDIA. Must know AWS, Kubernetes,"
                    " Terraform, CI/CD pipelines, and GitOps workflows.</p>"
                )
            }
        }
        with patch("sources.workday.aiohttp.ClientSession",
                   return_value=_mock_session(payload)):
            n = await fetch_descriptions(jobs)
        assert n == 1
        assert jobs[0].description is not None
        assert "Cloud Engineer" in jobs[0].description

    @pytest.mark.asyncio
    async def test_no_fill_on_404(self):
        jobs = [_wd_job()]
        with patch("sources.workday.aiohttp.ClientSession",
                   return_value=_mock_session({}, status=404)):
            n = await fetch_descriptions(jobs)
        assert n == 0
        assert jobs[0].description is None

    @pytest.mark.asyncio
    async def test_progress_callback_fires_per_job(self):
        jobs = [_wd_job(url=f"https://nvidia.wd5.myworkdayjobs.com/en-US/X/job/J{i}")
                for i in range(3)]
        payload = {
            "jobPostingInfo": {
                "jobDescription": "<p>" + "x" * 200 + "</p>",
            }
        }
        ticks: list[int] = []
        with patch("sources.workday.aiohttp.ClientSession",
                   return_value=_mock_session(payload)):
            await fetch_descriptions(jobs, on_progress=lambda n: ticks.append(n))
        assert sum(ticks) == 3

    @pytest.mark.asyncio
    async def test_unparseable_url_skips_gracefully(self):
        jobs = [_wd_job(url="not-a-workday-url")]
        n = await fetch_descriptions(jobs)
        assert n == 0
        assert jobs[0].description is None
