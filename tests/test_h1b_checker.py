"""Tests for H1B sponsor check — DB cache, normalization, scraping, check_batch."""
from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from db.database import Database
from models.job import RawJob


def _make_db() -> Database:
    db = Database(":memory:")
    db.initialize()
    return db


def _mock_session(html_by_year: dict[int, str]):
    """Return a mock aiohttp.ClientSession whose get() returns HTML keyed by year."""

    def make_resp(html: str):
        resp = MagicMock()
        resp.text = AsyncMock(return_value=html)
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=None)
        return resp

    def get(url, **kwargs):
        for year, html in html_by_year.items():
            if str(year) in url:
                return make_resp(html)
        return make_resp("<html></html>")

    session = MagicMock()
    session.get = get
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


def _make_job(company: str, source: str = "linkedin") -> RawJob:
    return RawJob(
        title="Cloud Engineer",
        company=company,
        location="Remote",
        url="https://example.com/job",
        source=source,
        description="We use AWS and Kubernetes.",
    )


class TestRawJobH1BField(unittest.TestCase):
    def test_field_defaults_to_none(self):
        job = _make_job("Stripe")
        assert job.h1b_sponsor_verified is None

    def test_field_can_be_set_true(self):
        job = _make_job("Stripe")
        job.h1b_sponsor_verified = True
        assert job.h1b_sponsor_verified is True

    def test_field_can_be_set_false(self):
        job = _make_job("Stripe")
        job.h1b_sponsor_verified = False
        assert job.h1b_sponsor_verified is False


class TestH1BCacheDB(unittest.TestCase):
    def test_get_returns_none_on_miss(self):
        db = _make_db()
        assert db.get_h1b_cache("stripe") is None

    def test_set_then_get_returns_bool(self):
        db = _make_db()
        db.set_h1b_cache("stripe", "Stripe, Inc.", True)
        assert db.get_h1b_cache("stripe") is True

    def test_set_false_then_get_returns_false(self):
        db = _make_db()
        db.set_h1b_cache("nosponsco", "NoSponsCo", False)
        assert db.get_h1b_cache("nosponsco") is False

    def test_get_returns_none_when_expired(self):
        db = _make_db()
        old_ts = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        db.conn.execute(
            "INSERT INTO h1b_sponsor_cache (company_key, company_raw, verified, checked_at)"
            " VALUES (?, ?, ?, ?)",
            ("oldco", "OldCo", 1, old_ts),
        )
        db.conn.commit()
        assert db.get_h1b_cache("oldco") is None

    def test_upsert_overwrites_expired(self):
        db = _make_db()
        old_ts = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        db.conn.execute(
            "INSERT INTO h1b_sponsor_cache (company_key, company_raw, verified, checked_at)"
            " VALUES (?, ?, ?, ?)",
            ("stripe", "Stripe", 0, old_ts),
        )
        db.conn.commit()
        db.set_h1b_cache("stripe", "Stripe", True)
        assert db.get_h1b_cache("stripe") is True


class TestH1BCheckerNormalize(unittest.TestCase):
    def test_strips_inc_suffix(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker._normalize("Stripe, Inc.") == "stripe"

    def test_strips_llc_suffix(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker._normalize("Meta Platforms LLC") == "meta platforms"

    def test_no_suffix(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker._normalize("ServiceNow") == "servicenow"

    def test_strips_corp(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker._normalize("Oracle Corp") == "oracle"

    def test_strips_limited(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker._normalize("Tata Consultancy Services Limited") == "tata consultancy services"

    def test_collapses_extra_whitespace(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker._normalize("  Google  LLC  ") == "google"


class TestH1BCheckerHasResults(unittest.TestCase):
    def test_no_data_string_returns_false(self):
        from screening.h1b_checker import H1BChecker
        html = "<html><body><table><tbody>No data available in table</tbody></table></body></html>"
        assert H1BChecker._has_results(html) is False

    def test_tbody_with_tr_returns_true(self):
        from screening.h1b_checker import H1BChecker
        html = "<html><body><table><tbody><tr><td>STRIPE INC</td></tr></tbody></table></body></html>"
        assert H1BChecker._has_results(html) is True

    def test_empty_tbody_returns_false(self):
        from screening.h1b_checker import H1BChecker
        html = "<html><body><table><tbody></tbody></table></body></html>"
        assert H1BChecker._has_results(html) is False


class TestH1BCheckerScrape(unittest.TestCase):
    def test_scrape_year_returns_true_when_rows(self):
        from screening.h1b_checker import H1BChecker
        html_with_rows = (
            "<html><table><tbody><tr><td>STRIPE INC</td></tr></tbody></table></html>"
        )
        session = _mock_session({2025: html_with_rows})
        checker = H1BChecker(_make_db())

        result = asyncio.run(checker._scrape_year(session, "stripe", 2025))
        assert result is True

    def test_scrape_year_returns_false_when_no_data(self):
        from screening.h1b_checker import H1BChecker
        html_no_data = (
            "<html><table><tbody>No data available in table</tbody></table></html>"
        )
        session = _mock_session({2025: html_no_data})
        checker = H1BChecker(_make_db())

        result = asyncio.run(checker._scrape_year(session, "noco", 2025))
        assert result is False

    def test_check_company_returns_true_if_current_year_has_data(self):
        from screening.h1b_checker import H1BChecker
        current_year = datetime.now(timezone.utc).year
        html_rows = "<html><table><tbody><tr><td>X</td></tr></tbody></table></html>"
        html_none = "<html><table><tbody>No data available in table</tbody></table></html>"
        session = _mock_session({current_year: html_rows, current_year - 1: html_none})
        checker = H1BChecker(_make_db())
        sem = asyncio.Semaphore(3)

        result = asyncio.run(checker._check_company(sem, session, "stripe", "Stripe"))
        assert result is True

    def test_check_company_returns_false_if_both_years_empty(self):
        from screening.h1b_checker import H1BChecker
        current_year = datetime.now(timezone.utc).year
        html_none = "<html><table><tbody>No data available in table</tbody></table></html>"
        session = _mock_session({current_year: html_none, current_year - 1: html_none})
        checker = H1BChecker(_make_db())
        sem = asyncio.Semaphore(3)

        result = asyncio.run(checker._check_company(sem, session, "noco", "NoCo"))
        assert result is False

    def test_check_company_returns_none_on_exception(self):
        from screening.h1b_checker import H1BChecker

        async def boom(*args, **kwargs):
            raise aiohttp.ClientError("network failure")

        checker = H1BChecker(_make_db())
        checker._scrape_year = boom
        sem = asyncio.Semaphore(3)
        session = MagicMock()

        result = asyncio.run(checker._check_company(sem, session, "errco", "ErrCo"))
        assert result is None


class TestH1BCheckerBatch(unittest.TestCase):
    def test_curated_sources_are_skipped(self):
        from screening.h1b_checker import H1BChecker
        checker = H1BChecker(_make_db())
        jobs = [
            _make_job("Anthropic", source="greenhouse-anthropic"),
            _make_job("Scale AI", source="lever-scaleai"),
            _make_job("Weights & Biases", source="ashby-wandb"),
        ]
        asyncio.run(checker.check_batch(jobs))
        for job in jobs:
            assert job.h1b_sponsor_verified is None

    def test_open_source_job_gets_verified_true(self):
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch

        db = _make_db()
        checker = H1BChecker(db)
        job = _make_job("Stripe", source="linkedin")

        async def fake_check(sem, session, key, raw):
            return True

        with patch.object(checker, "_check_company", side_effect=fake_check):
            asyncio.run(checker.check_batch([job]))

        assert job.h1b_sponsor_verified is True

    def test_open_source_job_gets_verified_false(self):
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch

        db = _make_db()
        checker = H1BChecker(db)
        job = _make_job("TinyStartup", source="remoteok")

        async def fake_check(sem, session, key, raw):
            return False

        with patch.object(checker, "_check_company", side_effect=fake_check):
            asyncio.run(checker.check_batch([job]))

        assert job.h1b_sponsor_verified is False

    def test_error_result_leaves_field_none(self):
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch

        db = _make_db()
        checker = H1BChecker(db)
        job = _make_job("ErrCo", source="hackernews")

        async def fake_check(sem, session, key, raw):
            return None

        with patch.object(checker, "_check_company", side_effect=fake_check):
            asyncio.run(checker.check_batch([job]))

        assert job.h1b_sponsor_verified is None

    def test_cache_hit_skips_scrape(self):
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch

        db = _make_db()
        db.set_h1b_cache("stripe", "Stripe", True)
        checker = H1BChecker(db)
        job = _make_job("Stripe", source="linkedin")

        call_count = 0

        async def fake_check(sem, session, key, raw):
            nonlocal call_count
            call_count += 1
            return False

        with patch.object(checker, "_check_company", side_effect=fake_check):
            asyncio.run(checker.check_batch([job]))

        assert call_count == 0
        assert job.h1b_sponsor_verified is True

    def test_same_company_deduplicated(self):
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch

        db = _make_db()
        checker = H1BChecker(db)
        jobs = [
            _make_job("Stripe", source="linkedin"),
            _make_job("Stripe, Inc.", source="indeed"),
        ]

        call_count = 0

        async def fake_check(sem, session, key, raw):
            nonlocal call_count
            call_count += 1
            return True

        with patch.object(checker, "_check_company", side_effect=fake_check):
            asyncio.run(checker.check_batch(jobs))

        assert call_count == 1
        assert all(j.h1b_sponsor_verified is True for j in jobs)

    def test_verified_result_is_cached(self):
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch

        db = _make_db()
        checker = H1BChecker(db)
        job = _make_job("Datadog", source="linkedin")

        async def fake_check(sem, session, key, raw):
            return False

        with patch.object(checker, "_check_company", side_effect=fake_check):
            asyncio.run(checker.check_batch([job]))

        assert db.get_h1b_cache("datadog") is False

    def test_none_result_is_not_cached(self):
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch

        db = _make_db()
        checker = H1BChecker(db)
        job = _make_job("ErrCo", source="remoteok")

        async def fake_check(sem, session, key, raw):
            return None

        with patch.object(checker, "_check_company", side_effect=fake_check):
            asyncio.run(checker.check_batch([job]))

        assert db.get_h1b_cache("errco") is None

    def test_empty_company_name_is_skipped(self):
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch

        db = _make_db()
        checker = H1BChecker(db)
        # A job whose company normalizes to empty string (e.g., just "Inc.")
        job = RawJob(
            title="Cloud Engineer",
            company="Inc.",
            location="Remote",
            url="https://example.com/job",
            source="linkedin",
            description="We use AWS.",
        )

        call_count = 0

        async def fake_check(sem, session, key, raw):
            nonlocal call_count
            call_count += 1
            return True

        with patch.object(checker, "_check_company", side_effect=fake_check):
            asyncio.run(checker.check_batch([job]))

        assert call_count == 0  # skipped — no meaningful key
        assert job.h1b_sponsor_verified is None  # left untouched
