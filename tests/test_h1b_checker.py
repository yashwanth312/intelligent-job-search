"""Tests for H1B sponsor check — DB cache, normalization, scraping, check_batch."""
from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

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
