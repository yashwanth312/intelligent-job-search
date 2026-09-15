"""Tests for WorkdayAdapter."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sources.workday import WorkdayAdapter, _resolve_location
from sources._dates import parse_workday_relative

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
                "postedOn": "Posted Today",
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
        # Regression guard: postedOn is a display string, not ISO — this used
        # to come back None (parse_iso choked on it) and get dropped as stale.
        assert jobs[0].posted_at is not None

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

    @pytest.mark.asyncio
    async def test_multi_location_posting_decodes_location_from_url(self):
        # Regression guard: Workday's search API collapses a job posted to
        # several locations down to "2 Locations" in locationsText, which
        # used to sail through Stage 1's location filter unfiltered even
        # when the job is entirely non-US. The public URL always encodes
        # one concrete location right after "job/" — decode that instead.
        adapter = WorkdayAdapter(companies=[COMPANY])
        resp = _mock_resp(200, {
            "total": 1,
            "jobPostings": [{
                "title": "Field Service AI Technical Architect",
                "externalPath": "job/India---Gurgaon/Field-Service-AI_JR335049",
                "locationsText": "2 Locations",
                "postedOn": "Posted Today",
            }],
        })
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncCM(resp))

        with patch("asyncio.sleep"):
            jobs, _ = await adapter._scrape_company(
                mock_session, COMPANY, ["Field Service AI Technical Architect"]
            )

        assert len(jobs) == 1
        assert jobs[0].location == "India - Gurgaon"


class TestResolveLocation:
    def test_normal_locations_text_passes_through(self):
        assert _resolve_location("Austin, Texas", "job/Austin-TX/x_JR1") == "Austin, Texas"

    def test_n_locations_falls_back_to_url_slug(self):
        assert _resolve_location(
            "3 Locations", "job/United-Kingdom---London/x_JR1"
        ) == "United Kingdom - London"

    def test_n_locations_case_insensitive_and_singular(self):
        assert _resolve_location("1 location", "job/Israel-Yokneam/x_JR1") == "Israel Yokneam"

    def test_empty_locations_text_falls_back_to_url_slug(self):
        assert _resolve_location("", "job/Riyadh---MSO/x_JR1") == "Riyadh - MSO"

    def test_unparseable_external_path_returns_original_text(self):
        assert _resolve_location("2 Locations", "not-a-job-path") == "2 Locations"


class TestParseWorkdayRelative:
    def test_posted_today_is_fresh(self):
        result = parse_workday_relative("Posted Today")
        now = datetime.now(timezone.utc)
        assert result is not None
        assert (now - result) < timedelta(minutes=1)

    def test_posted_yesterday_is_one_day_back(self):
        result = parse_workday_relative("Posted Yesterday")
        now = datetime.now(timezone.utc)
        assert result is not None
        assert timedelta(hours=23) < (now - result) < timedelta(hours=25)

    def test_posted_n_days_ago(self):
        result = parse_workday_relative("Posted 7 Days Ago")
        now = datetime.now(timezone.utc)
        assert result is not None
        assert timedelta(days=6, hours=23) < (now - result) < timedelta(days=7, hours=1)

    def test_posted_30_plus_days_ago(self):
        result = parse_workday_relative("Posted 30+ Days Ago")
        now = datetime.now(timezone.utc)
        assert result is not None
        assert (now - result) >= timedelta(days=29, hours=23)

    def test_case_insensitive(self):
        assert parse_workday_relative("posted today") is not None

    def test_unparseable_returns_none(self):
        assert parse_workday_relative("some garbage string") is None
        assert parse_workday_relative(None) is None
        assert parse_workday_relative("") is None

    def test_iso_string_is_not_matched(self):
        # Confirms this really is a different code path from parse_iso —
        # an actual ISO date isn't one of Workday's real formats and should
        # fall through to None (safe-stale), not be silently accepted.
        assert parse_workday_relative("2026-04-25") is None
