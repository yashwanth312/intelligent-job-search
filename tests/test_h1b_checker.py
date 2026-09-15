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

        # _scrape_year streams the body and stops as soon as a result row shows
        # up, so the mock has to expose content.iter_chunked, not just text().
        def iter_chunked(size: int):
            async def gen():
                data = html.encode()
                for i in range(0, max(len(data), 1), size):
                    yield data[i : i + size]
            return gen()

        resp.content.iter_chunked = iter_chunked
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


class TestH1BDecoratedCompanyNames(unittest.TestCase):
    """Regression cover for the brand-variant false negatives.

    h1bdata.info prefix-matches the legal filer name, so a decorated job-board
    company string ("Amazon Web Services (AWS)") matched nothing and was cached
    as a non-sponsor — silently dropping every posting from that employer.
    """

    def test_parenthetical_is_stripped_from_cache_key(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker._normalize("Amazon Web Services (AWS)") == "amazon web services"

    def test_tagline_is_stripped(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker._normalize("Hakkoda, an IBM Company") == "hakkoda"
        assert H1BChecker._normalize("N2 Lab | Oracle NetSuite Alliance Partner") == "n2 lab"

    def test_trailing_legal_suffix_is_stripped(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker._normalize("Deloitte Consulting LLP") == "deloitte consulting"

    def test_legal_suffix_is_not_stripped_mid_name(self):
        from screening.h1b_checker import H1BChecker
        # "Company" heads no suffix here — the name must survive intact.
        assert H1BChecker._normalize("Corporation Service Company") == "corporation service company"

    def test_name_that_is_only_a_suffix_yields_no_key(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker._normalize("Inc.") == ""
        assert H1BChecker._normalize("LLC") == ""

    def test_ampersand_becomes_a_space(self):
        from screening.h1b_checker import H1BChecker
        # h1bdata matches "AT&T" only as "at t" — "att" returns nothing.
        assert H1BChecker._query_forms("AT&T") == ["at t"]

    def test_dot_variants_are_both_tried(self):
        from screening.h1b_checker import H1BChecker
        # h1bdata stores "AMAZONCOM SERVICES LLC", so the dot-dropped form must
        # come first, but the spaced form is worth a fallback.
        assert H1BChecker._query_forms("Amazon.com") == ["amazoncom", "amazon com"]

    def test_generic_tail_tokens_are_peeled_toward_the_parent_brand(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker._query_forms("NVIDIA AI") == ["nvidia ai", "nvidia"]
        assert H1BChecker._query_forms("KPMG US") == ["kpmg us", "kpmg"]
        assert H1BChecker._query_forms("NTT DATA North America") == [
            "ntt data north america", "ntt data north", "ntt data",
        ]

    def test_bare_root_is_only_reached_by_peeling_decoration(self):
        from screening.h1b_checker import H1BChecker
        # "Prime" is not reachable by peeling generic tails alone, so it is never
        # queried on its own — a one-token prefix that broad would match anything.
        forms = H1BChecker._query_forms("Prime Video & Amazon MGM Studios")
        assert "prime" not in forms

    def test_short_or_generic_roots_are_never_queried_bare(self):
        from screening.h1b_checker import H1BChecker
        assert "n2" not in H1BChecker._query_forms("N2 Lab")
        assert "data" not in H1BChecker._query_forms("Data Systems")

    def test_query_ladder_is_bounded(self):
        from screening.h1b_checker import H1BChecker
        forms = H1BChecker._query_forms("Foo Global Technologies Solutions Services Group")
        assert len(forms) <= 4


class TestH1BBrandInheritance(unittest.TestCase):
    """A decorated variant of a confirmed sponsor inherits the parent's verdict."""

    def _checker_with_keys(self, roots: set[str]):
        from screening.h1b_checker import H1BChecker
        checker = H1BChecker(_make_db())
        checker._verified_keys = roots
        return checker

    def test_variant_of_verified_sponsor_inherits(self):
        checker = self._checker_with_keys({"amazon", "nvidia", "microsoft"})
        assert checker._inherits_sponsor("amazon web services") is True
        assert checker._inherits_sponsor("nvidia ai") is True
        assert checker._inherits_sponsor("microsoft ai") is True

    def test_unrelated_company_does_not_inherit(self):
        checker = self._checker_with_keys({"amazon"})
        assert checker._inherits_sponsor("stealth startup") is False
        assert checker._inherits_sponsor("jobs via dice") is False

    def test_single_token_name_never_inherits(self):
        # "amazon" itself must be scraped, not inherit from its own cache row.
        checker = self._checker_with_keys({"amazon"})
        assert checker._inherits_sponsor("amazon") is False

    def test_generic_or_short_root_never_inherits(self):
        checker = self._checker_with_keys({"data", "ibm", "talent"})
        assert checker._inherits_sponsor("data systems inc") is False
        assert checker._inherits_sponsor("ibm consulting") is False
        assert checker._inherits_sponsor("talent groups") is False

    def test_inheritance_skips_the_scrape_and_caches_the_result(self):
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch

        db = _make_db()
        db.set_h1b_cache("nvidia", "NVIDIA", True)
        checker = H1BChecker(db)
        job = _make_job("NVIDIA AI")

        calls = []

        async def fake_check(sem, session, key, raw):
            calls.append(key)
            return False

        with patch.object(checker, "_check_company", side_effect=fake_check):
            asyncio.run(checker.check_batch([job]))

        assert calls == []                       # never hit the network
        assert job.h1b_sponsor_verified is True
        assert db.get_h1b_cache("nvidia ai") is True


class TestH1BAsymmetricCacheTTL(unittest.TestCase):
    """Negatives expire sooner than positives so a wrong drop self-heals."""

    def _age_entry(self, db, key: str, days: int) -> None:
        stale = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        db.conn.execute(
            "UPDATE h1b_sponsor_cache SET checked_at = ? WHERE company_key = ?",
            (stale, key),
        )
        db.conn.commit()

    def test_negative_expires_before_positive(self):
        from config import H1B_CACHE_TTL_DAYS, H1B_NEGATIVE_CACHE_TTL_DAYS
        assert H1B_NEGATIVE_CACHE_TTL_DAYS < H1B_CACHE_TTL_DAYS

        db = _make_db()
        db.set_h1b_cache("sponsor co", "Sponsor Co", True)
        db.set_h1b_cache("ghost co", "Ghost Co", False)

        age = H1B_NEGATIVE_CACHE_TTL_DAYS + 1
        self._age_entry(db, "sponsor co", age)
        self._age_entry(db, "ghost co", age)

        assert db.get_h1b_cache("sponsor co") is True   # still trusted
        assert db.get_h1b_cache("ghost co") is None     # re-check it

    def test_verified_roots_lookup_returns_only_sponsors(self):
        db = _make_db()
        db.set_h1b_cache("nvidia", "NVIDIA", True)
        db.set_h1b_cache("ghost co", "Ghost Co", False)
        assert db.get_verified_sponsor_keys() == {"nvidia"}


class TestH1BInheritanceBeatsStaleNegative(unittest.TestCase):
    def test_cached_false_does_not_block_brand_inheritance(self):
        """A stale bad negative must not outrank a confirmed parent brand.

        This is the exact shape of the original bug: "Amazon Web Services (AWS)"
        was cached False, so every AWS posting was dropped even though "Amazon"
        was sitting in the same cache as a confirmed sponsor.
        """
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch

        db = _make_db()
        db.set_h1b_cache("amazon", "Amazon", True)
        db.set_h1b_cache("amazon web services", "Amazon Web Services (AWS)", False)

        checker = H1BChecker(db)
        job = _make_job("Amazon Web Services (AWS)")

        with patch.object(checker, "_check_company", side_effect=AssertionError("should not scrape")):
            asyncio.run(checker.check_batch([job]))

        assert job.h1b_sponsor_verified is True
        assert db.get_h1b_cache("amazon web services") is True

    def test_cached_false_still_wins_for_unrelated_company(self):
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch

        db = _make_db()
        db.set_h1b_cache("amazon", "Amazon", True)
        db.set_h1b_cache("ghost staffing", "Ghost Staffing LLC", False)

        checker = H1BChecker(db)
        job = _make_job("Ghost Staffing LLC")

        with patch.object(checker, "_check_company", side_effect=AssertionError("should not scrape")):
            asyncio.run(checker.check_batch([job]))

        assert job.h1b_sponsor_verified is False


class TestH1BInheritanceRequiresFullParentKey(unittest.TestCase):
    """Inheritance matches a sponsor's whole key, not just a shared first word.

    With thousands of sponsors cached, leading tokens collide constantly. Keying
    on the root alone waved through ~1,160 unrelated companies (staffing firms
    sharing a first word with a real sponsor) before this was tightened.
    """

    def _checker(self, keys: set[str]):
        from screening.h1b_checker import H1BChecker
        checker = H1BChecker(_make_db())
        checker._verified_keys = keys
        return checker

    def test_shared_first_word_alone_does_not_inherit(self):
        # "allied technologies" is a sponsor; "allied universal" is not the same firm.
        checker = self._checker({"allied technologies"})
        assert checker._inherits_sponsor("allied universal") is False

    def test_exact_parent_key_inherits(self):
        checker = self._checker({"allied technologies"})
        assert checker._inherits_sponsor("allied technologies federal") is True

    def test_longer_parent_prefix_is_matched(self):
        checker = self._checker({"amazon web"})
        assert checker._inherits_sponsor("amazon web services") is True
