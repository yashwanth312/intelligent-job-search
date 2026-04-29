from datetime import datetime, timezone

from sources._dates import parse_epoch, parse_iso


class TestParseIso:
    def test_z_suffix(self):
        dt = parse_iso("2026-04-15T10:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt == datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)

    def test_with_offset(self):
        dt = parse_iso("2026-04-15T10:00:00+00:00")
        assert dt == datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)

    def test_naive_assumed_utc(self):
        dt = parse_iso("2026-04-15T10:00:00")
        assert dt is not None
        assert dt.tzinfo is timezone.utc

    def test_none(self):
        assert parse_iso(None) is None
        assert parse_iso("") is None

    def test_bad_string(self):
        assert parse_iso("not a date") is None


class TestParseEpoch:
    def test_seconds(self):
        dt = parse_epoch(1713200000)
        assert dt is not None
        assert dt.tzinfo is timezone.utc

    def test_milliseconds(self):
        dt_s = parse_epoch(1713200000)
        dt_ms = parse_epoch(1713200000000, ms=True)
        assert dt_s == dt_ms

    def test_none(self):
        assert parse_epoch(None) is None

    def test_bad_value(self):
        assert parse_epoch("abc") is None
