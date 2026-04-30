"""Tests for the Workday candidate promotion decision logic.

The HTTP probe and h1bdata.info checks are exercised by the script itself
against real services; here we test the disposition rules in isolation.
"""
from __future__ import annotations

import importlib.util
import pathlib

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


class TestDecide:
    def test_both_pass_promotes(self):
        assert _decide(h1b=True, board_alive=True) == "promote"

    def test_both_fail_rejects(self):
        assert _decide(h1b=False, board_alive=False) == "reject"

    def test_dead_board_rejects_even_when_h1b_passes(self):
        # Can't scrape what doesn't respond, regardless of sponsorship.
        assert _decide(h1b=True, board_alive=False) == "reject"

    def test_no_h1b_history_with_alive_board_rejects(self):
        # Definitive "no h1b" + working board = clear signal company won't sponsor.
        assert _decide(h1b=False, board_alive=True) == "reject"

    def test_h1b_unknown_retries(self):
        # Network/parse error on h1bdata.info -> ambiguous, retry.
        assert _decide(h1b=None, board_alive=True) == "retry"

    def test_board_unknown_retries(self):
        # Transient HTTP error on Workday -> ambiguous, retry.
        assert _decide(h1b=True, board_alive=None) == "retry"

    def test_both_unknown_retries(self):
        assert _decide(h1b=None, board_alive=None) == "retry"

    def test_h1b_unknown_board_dead_rejects(self):
        # Dead board is definitive; h1b ambiguity doesn't save it.
        assert _decide(h1b=None, board_alive=False) == "reject"

    def test_h1b_no_history_board_unknown_retries(self):
        # h1b said no but board response was ambiguous -> wait for clearer signal.
        assert _decide(h1b=False, board_alive=None) == "retry"
