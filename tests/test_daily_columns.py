"""Tests for Daily tab column count, order, and key positions."""
from __future__ import annotations

from config import DAILY_HEADERS


EXPECTED_HEADERS = [
    "Company",          # 0
    "Job Title",        # 1
    "Location",         # 2
    "Confidence",       # 3
    "Status",           # 4
    "Risk Flags",       # 5  ← moved up from col 11
    "Apply Link",       # 6
    "Posted",           # 7
    "Source",           # 8
    "AI Reasoning",     # 9
    "Suggested Angle",  # 10
    "Match Signals",    # 11
    "Sponsorship",      # 12 ← new
    "Salary Range",     # 13
    "Notes",            # 14
]


def test_daily_headers_exact_match():
    assert DAILY_HEADERS == EXPECTED_HEADERS


def test_daily_headers_count_is_15():
    assert len(DAILY_HEADERS) == 15


def test_status_is_at_index_4():
    assert DAILY_HEADERS[4] == "Status"


def test_risk_flags_immediately_follows_status():
    assert DAILY_HEADERS[5] == "Risk Flags"


def test_sponsorship_is_at_index_12():
    assert DAILY_HEADERS[12] == "Sponsorship"
