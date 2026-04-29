"""Shared date parsing helpers for source adapters.

All functions return tz-aware UTC datetimes so the orchestrator can
compare ages consistently across sources.
"""
from __future__ import annotations

from datetime import datetime, timezone


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


def parse_epoch(value, *, ms: bool = False) -> datetime | None:
    """Parse a unix epoch (seconds or ms) into tz-aware UTC."""
    if value is None:
        return None
    try:
        ts = float(value) / (1000.0 if ms else 1.0)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, TypeError, OSError, OverflowError):
        return None
