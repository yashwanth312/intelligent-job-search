"""Tests for the Workday candidate promotion decision logic.

The HTTP probe is exercised by the script itself against real services; here
we test the disposition rules in isolation. Promotion gates on domain relevance
only — sponsorship is enforced at scrape time, since workday-* is a droppable
source that screening/h1b_checker.py already checks on every posting.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

# Load the script as a module without requiring it to be in a package.
_PROMOTE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "scripts" / "promote_workday_candidates.py"
)
_spec = importlib.util.spec_from_file_location(
    "promote_workday_candidates", _PROMOTE_PATH
)
_promoter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_promoter)

_decide = _promoter._decide
MIN = _promoter.MIN_DOMAIN_HITS


class TestDecide:
    """Promotion is gated on domain relevance in every case."""

    def test_alive_with_enough_domain_roles_promotes(self):
        assert _decide(h1b=None, board_alive=True, domain_hits=MIN) == ("promote", "")

    def test_zero_domain_roles_rejects(self):
        # Truly off-domain (banks/hospitals) — reject so discovery stops it.
        assert _decide(h1b=None, board_alive=True, domain_hits=0) == (
            "reject", "no_domain_roles",
        )

    def test_sub_bar_but_nonzero_is_held(self):
        # Some real domain roles but below the promote bar -> hold, never nuked.
        assert _decide(h1b=None, board_alive=True, domain_hits=MIN - 1) == ("hold", "")
        assert _decide(h1b=None, board_alive=True, domain_hits=1) == ("hold", "")

    def test_dead_board_always_rejects(self):
        assert _decide(h1b=True, board_alive=False, domain_hits=99) == (
            "reject", "dead_board",
        )

    def test_board_unknown_retries(self):
        assert _decide(h1b=None, board_alive=None, domain_hits=0) == ("retry", "")


class TestH1BNoLongerGatesPromotion:
    """Regression: the old gate got this backwards in both directions.

    It promoted tenants with zero engineering roles because they had LCA
    filings, and rejected genuinely on-domain employers (Valeo, 8 domain hits)
    because they had none.
    """

    def test_sponsor_with_no_domain_roles_is_not_promoted(self):
        assert _decide(h1b=True, board_alive=True, domain_hits=0) == (
            "reject", "no_domain_roles",
        )

    def test_non_sponsor_with_domain_roles_is_promoted(self):
        assert _decide(h1b=False, board_alive=True, domain_hits=MIN) == ("promote", "")

    def test_unknown_h1b_does_not_force_a_retry(self):
        assert _decide(h1b=None, board_alive=True, domain_hits=MIN) == ("promote", "")
