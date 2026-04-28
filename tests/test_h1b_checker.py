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
