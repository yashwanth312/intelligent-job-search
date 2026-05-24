"""Tests for helper functions extracted from main.py."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


async def _never_returns(*args, **kwargs):
    """Coroutine that never completes — simulates a hung H1B checker."""
    await asyncio.sleep(9999)


@pytest.mark.asyncio
async def test_h1b_timeout_continues_without_raising():
    """When H1B checker hangs, the helper catches TimeoutError and returns normally."""
    from main import _h1b_check_with_timeout
    checker = MagicMock()
    checker.check_batch = _never_returns
    # timeout=0.01s ensures it fires immediately; must not raise
    await _h1b_check_with_timeout(checker, [], timeout=0.01)


@pytest.mark.asyncio
async def test_h1b_timeout_calls_checker_normally_when_fast():
    """When H1B checker completes quickly, it is called exactly once."""
    from main import _h1b_check_with_timeout
    checker = MagicMock()
    checker.check_batch = AsyncMock()
    await _h1b_check_with_timeout(checker, [], timeout=5)
    checker.check_batch.assert_called_once_with([])
