"""Shared date parsing helpers for source adapters.

All functions return tz-aware UTC datetimes so the orchestrator can
compare ages consistently across sources.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone


def parse_iso(value) -> datetime | None:
    """Parse an ISO-8601 string (with or without 'Z') into tz-aware UTC."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        s = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


_WORKDAY_DAYS_AGO_RE = re.compile(r"posted\s+(\d+)\+?\s*days?\s+ago", re.IGNORECASE)


def parse_workday_relative(value) -> datetime | None:
    """Parse Workday's `postedOn` display string ("Posted Today", "Posted
    Yesterday", "Posted N Days Ago", "Posted 30+ Days Ago") into a tz-aware
    UTC datetime.

    The public Workday jobs API doesn't return an ISO date here — it's a
    human-facing string — so `parse_iso()` silently failed on every single
    Workday posting, which `filter_fresh_jobs` then treated as unproven-fresh
    and dropped as stale (Workday isn't a prefiltered source). That's been
    true for 5+ months across 92 tenants. Returns None (same safe-stale
    fallback as before) for anything that doesn't match one of these formats.
    """
    if not value:
        return None
    s = str(value).strip().lower()
    now = datetime.now(timezone.utc)
    if s in ("posted today", "today"):
        return now
    if s in ("posted yesterday", "yesterday"):
        return now - timedelta(days=1)
    m = _WORKDAY_DAYS_AGO_RE.search(s)
    if m:
        return now - timedelta(days=int(m.group(1)))
    return None


def parse_epoch(value, *, ms: bool = False) -> datetime | None:
    """Parse a unix epoch (seconds or ms) into tz-aware UTC."""
    if value is None:
        return None
    try:
        ts = float(value) / (1000.0 if ms else 1.0)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, TypeError, OSError, OverflowError):
        return None
