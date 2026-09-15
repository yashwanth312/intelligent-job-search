"""Tests for Daily tab column count, order, and key positions."""
from __future__ import annotations

from config import DAILY_HEADERS


EXPECTED_HEADERS = [
    "Company",              # 0
    "Job Title",            # 1
    "Location",             # 2
    "Confidence",           # 3
    "Status",               # 4
    "Interview Score (%)",  # 5  ← new
    "Risk Flags",           # 6  ← moved up from col 11
    "Apply Link",           # 7
    "Posted",               # 8
    "Source",               # 9
    "AI Reasoning",         # 10
    "Suggested Angle",      # 11
    "Match Signals",        # 12
    "Sponsorship",          # 13 ← new
    "Salary Range",         # 14
    "Notes",                # 15
]


def test_daily_headers_exact_match():
    assert DAILY_HEADERS == EXPECTED_HEADERS


def test_daily_headers_count_is_16():
    assert len(DAILY_HEADERS) == 16


def test_status_is_at_index_4():
    assert DAILY_HEADERS[4] == "Status"


def test_interview_score_immediately_follows_status():
    assert DAILY_HEADERS[5] == "Interview Score (%)"


def test_risk_flags_immediately_follows_interview_score():
    assert DAILY_HEADERS[6] == "Risk Flags"


def test_sponsorship_is_at_index_13():
    assert DAILY_HEADERS[13] == "Sponsorship"
