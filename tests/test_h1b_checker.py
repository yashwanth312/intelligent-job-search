"""Tests for H1B sponsor check — DB cache, normalization, LCA index lookup, check_batch."""
from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone

import pytest

from db.database import Database
from models.job import RawJob


def _make_db() -> Database:
    db = Database(":memory:")
    db.initialize()
    return db


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


def _index(*legal_names: str):
    """A real LcaIndex holding the given legal filer names, as the build script would."""
    from screening.h1b_checker import H1BChecker
    from screening.lca_index import LcaIndex
    return LcaIndex({H1BChecker.filer_key(n) for n in legal_names})


def _checker(db, *legal_names: str):
    from screening.h1b_checker import H1BChecker
    return H1BChecker(db, index=_index(*legal_names))


class TestH1BFilerKey(unittest.TestCase):
    def test_legal_suffix_is_stripped(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker.filer_key("IBM Corporation") == "ibm"
        assert H1BChecker.filer_key("MICROSOFT CORPORATION") == "microsoft"

    def test_punctuation_and_spaces_are_dropped(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker.filer_key("JPMORGAN CHASE & CO.") == "jpmorganchase"
        assert H1BChecker.filer_key("Amazon.com Services LLC") == "amazoncomservices"

    def test_suffix_only_name_has_no_key(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker.filer_key("Inc.") == ""


class TestH1BCheckerBatch(unittest.TestCase):
    def test_sponsor_in_the_index_is_verified(self):
        """2026-10-04: h1bdata.info answered "0 records" for Microsoft, IBM and
        JPMorganChase, and all three were dropped as non-sponsors."""
        db = _make_db()
        checker = _checker(db, "MICROSOFT CORPORATION", "IBM Corporation",
                           "JPMORGAN CHASE & CO.")
        jobs = [_make_job("Microsoft"), _make_job("IBM"), _make_job("JPMorganChase")]

        asyncio.run(checker.check_batch(jobs))

        assert [j.h1b_sponsor_verified for j in jobs] == [True, True, True]

    def test_company_missing_from_the_index_is_not_a_sponsor(self):
        db = _make_db()
        checker = _checker(db, "MICROSOFT CORPORATION")
        job = _make_job("Ghost Staffing LLC")

        asyncio.run(checker.check_batch([job]))

        assert job.h1b_sponsor_verified is False
        assert db.get_h1b_cache("ghost staffing") is False

    def test_decorated_board_names_match_the_legal_filer(self):
        db = _make_db()
        checker = _checker(db, "Amazon Web Services, Inc.", "NVIDIA Corporation",
                           "Stripe, Inc.")
        jobs = [_make_job("Amazon Web Services (AWS)"), _make_job("NVIDIA AI"),
                _make_job("Stripe")]

        asyncio.run(checker.check_batch(jobs))

        assert all(j.h1b_sponsor_verified is True for j in jobs)

    def test_cached_negative_is_overruled_by_the_index(self):
        """The h1bdata-era negatives are wrong for big sponsors; the index decides."""
        db = _make_db()
        db.set_h1b_cache("microsoft", "Microsoft", False)
        checker = _checker(db, "MICROSOFT CORPORATION")
        job = _make_job("Microsoft")

        asyncio.run(checker.check_batch([job]))

        assert job.h1b_sponsor_verified is True
        assert db.get_h1b_cache("microsoft") is True

    def test_without_an_index_unknown_companies_stay_unverified(self):
        """No index means no evidence either way: keep the job, cache nothing."""
        from screening.h1b_checker import H1BChecker
        db = _make_db()
        db.set_h1b_cache("stripe", "Stripe", True)
        db.set_h1b_cache("ghost staffing", "Ghost Staffing", False)
        checker = H1BChecker(db, index=None)
        known, ghost, new = (_make_job("Stripe"), _make_job("Ghost Staffing"),
                             _make_job("BrandNewCo"))

        asyncio.run(checker.check_batch([known, ghost, new]))

        assert known.h1b_sponsor_verified is True
        assert ghost.h1b_sponsor_verified is None
        assert new.h1b_sponsor_verified is None
        assert db.get_h1b_cache("brandnewco") is None

    def test_board_sources_are_checked(self):
        """Board ATS jobs were exempt until 2026-10-03, which let known
        non-sponsors onto the Daily sheet. They now get the same check."""
        checker = _checker(_make_db(), "Anthropic, PBC", "Weights & Biases, Inc.")
        jobs = [
            _make_job("Anthropic", source="greenhouse-anthropic"),
            _make_job("Scale AI", source="lever-scaleai"),
            _make_job("Weights & Biases", source="ashby-wandb"),
        ]

        asyncio.run(checker.check_batch(jobs))

        assert [j.h1b_sponsor_verified for j in jobs] == [True, False, True]

    def test_same_company_variants_share_one_verdict(self):
        checker = _checker(_make_db(), "Stripe, Inc.")
        jobs = [_make_job("Stripe", source="linkedin"),
                _make_job("Stripe, Inc.", source="indeed")]

        asyncio.run(checker.check_batch(jobs))

        assert all(j.h1b_sponsor_verified is True for j in jobs)

    def test_empty_company_name_is_skipped(self):
        db = _make_db()
        checker = _checker(db, "Inc. Holdings")
        # A job whose company normalizes to empty string (e.g., just "Inc.")
        job = RawJob(
            title="Cloud Engineer",
            company="Inc.",
            location="Remote",
            url="https://example.com/job",
            source="linkedin",
            description="We use AWS.",
        )

        asyncio.run(checker.check_batch([job]))

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
        # "amazon" itself must be looked up, not inherit from its own cache row.
        checker = self._checker_with_keys({"amazon"})
        assert checker._inherits_sponsor("amazon") is False

    def test_generic_or_short_root_never_inherits(self):
        checker = self._checker_with_keys({"data", "ibm", "talent"})
        assert checker._inherits_sponsor("data systems inc") is False
        assert checker._inherits_sponsor("ibm consulting") is False
        assert checker._inherits_sponsor("talent groups") is False

    def test_inheritance_caches_the_result(self):
        db = _make_db()
        db.set_h1b_cache("nvidia", "NVIDIA", True)
        checker = _checker(db)  # empty index: only inheritance can verify it
        job = _make_job("NVIDIA AI")

        asyncio.run(checker.check_batch([job]))

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
        db = _make_db()
        db.set_h1b_cache("amazon", "Amazon", True)
        db.set_h1b_cache("amazon web services", "Amazon Web Services (AWS)", False)

        checker = _checker(db)
        job = _make_job("Amazon Web Services (AWS)")

        asyncio.run(checker.check_batch([job]))

        assert job.h1b_sponsor_verified is True
        assert db.get_h1b_cache("amazon web services") is True


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
