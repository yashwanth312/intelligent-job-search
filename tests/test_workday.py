"""Tests for WorkdayAdapter."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sources.workday import WorkdayAdapter

COMPANY = {
    "tenant": "testco",
    "wd_server": "wd5",
    "site": "TestCo_Careers",
    "name": "TestCo",
}


class AsyncCM:
    """Minimal async context manager for mocking aiohttp responses."""
    def __init__(self, value):
        self._value = value
    async def __aenter__(self):
        return self._value
    async def __aexit__(self, *args):
        pass


def _mock_resp(status: int, payload: dict) -> AsyncMock:
    r = AsyncMock()
    r.status = status
    r.json = AsyncMock(return_value=payload)
    return r


class TestWorkdayAdapter:
    @pytest.mark.asyncio
    async def test_scrape_converts_response_to_raw_jobs(self):
        adapter = WorkdayAdapter(companies=[COMPANY])
        resp = _mock_resp(200, {
            "total": 1,
            "jobPostings": [{
                "title": "Cloud Engineer",
                "externalPath": "job/Austin-TX/Cloud-Engineer_JR001",
                "locationsText": "Austin, Texas",
                "postedOn": "2026-04-25",
            }],
        })
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncCM(resp))

        with patch("asyncio.sleep"):
            jobs, errors = await adapter._scrape_company(
                mock_session, COMPANY, ["Cloud Engineer"]
            )

        assert len(jobs) == 1
        assert jobs[0].title == "Cloud Engineer"
        assert jobs[0].company == "TestCo"
        assert jobs[0].location == "Austin, Texas"
        assert jobs[0].source == "workday-testco"
        assert jobs[0].description is None
        assert "testco.wd5.myworkdayjobs.com/en-US/TestCo_Careers" in jobs[0].url
        assert "job/Austin-TX/Cloud-Engineer_JR001" in jobs[0].url
        assert errors == []

    @pytest.mark.asyncio
    async def test_pagination_fetches_all_pages(self):
        adapter = WorkdayAdapter(companies=[COMPANY])
        page1 = _mock_resp(200, {
            "total": 25,
            "jobPostings": [
                {"title": "Cloud Engineer", "externalPath": f"job/x_JR{i:03d}",
                 "locationsText": "Remote", "postedOn": "2026-04-25"}
                for i in range(20)
            ],
        })
        page2 = _mock_resp(200, {
            "total": 25,
            "jobPostings": [
                {"title": "Cloud Engineer", "externalPath": f"job/x_JR{i:03d}",
                 "locationsText": "Remote", "postedOn": "2026-04-25"}
                for i in range(20, 25)
            ],
        })
        mock_session = MagicMock()
        mock_session.post = MagicMock(
            side_effect=[AsyncCM(page1), AsyncCM(page2)]
        )

        with patch("asyncio.sleep"):
            jobs, _ = await adapter._scrape_company(
                mock_session, COMPANY, ["Cloud Engineer"]
            )

        assert mock_session.post.call_count == 2
        assert len(jobs) == 25

    @pytest.mark.asyncio
    async def test_429_triggers_backoff_and_succeeds_on_retry(self):
        adapter = WorkdayAdapter(companies=[COMPANY])
        r429 = AsyncMock()
        r429.status = 429
        r200 = _mock_resp(200, {
            "total": 1,
            "jobPostings": [{
                "title": "Cloud Engineer", "externalPath": "job/x_JR1",
                "locationsText": "Remote", "postedOn": "2026-04-25",
            }],
        })
        mock_session = MagicMock()
        mock_session.post = MagicMock(
            side_effect=[AsyncCM(r429), AsyncCM(r200)]
        )

        sleep_durations: list[float] = []
        with patch("asyncio.sleep", side_effect=lambda s: sleep_durations.append(s)):
            data, err = await adapter._post_with_retry(
                mock_session,
                "https://testco.wd5.myworkdayjobs.com/wday/cxs/testco/TestCo_Careers/jobs",
                {},
                "TestCo",
                "Cloud Engineer",
            )

        assert err is None
        assert data["total"] == 1
        assert any(s >= 30 for s in sleep_durations)

    @pytest.mark.asyncio
    async def test_non_200_non_429_returns_empty_no_error(self):
        adapter = WorkdayAdapter(companies=[COMPANY])
        r404 = AsyncMock()
        r404.status = 404
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncCM(r404))

        data, err = await adapter._post_with_retry(
            mock_session,
            "https://testco.wd5.myworkdayjobs.com/wday/cxs/testco/TestCo_Careers/jobs",
            {},
            "TestCo",
            "Cloud Engineer",
        )

        assert data == {}
        assert err is None

    @pytest.mark.asyncio
    async def test_job_url_contains_correct_components(self):
        company = {
            "tenant": "microsoft",
            "wd_server": "wd5",
            "site": "External_Careers",
            "name": "Microsoft",
        }
        adapter = WorkdayAdapter(companies=[company])
        resp = _mock_resp(200, {
            "total": 1,
            "jobPostings": [{
                "title": "Cloud Engineer",
                "externalPath": "job/Redmond-WA/Cloud-Engineer_JR12345",
                "locationsText": "Redmond, Washington",
                "postedOn": "2026-04-25",
            }],
        })
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncCM(resp))

        with patch("asyncio.sleep"):
            jobs, _ = await adapter._scrape_company(
                mock_session, company, ["Cloud Engineer"]
            )

        assert len(jobs) == 1
        expected_url = (
            "https://microsoft.wd5.myworkdayjobs.com/en-US/"
            "External_Careers/job/Redmond-WA/Cloud-Engineer_JR12345"
        )
        assert jobs[0].url == expected_url
