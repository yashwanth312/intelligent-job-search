"""Tests for source-aware drop partitioning in screening.h1b_checker."""
from __future__ import annotations

from models.job import RawJob
from screening.h1b_checker import is_droppable_source, partition_drops


def _job(source: str, verified: bool | None) -> RawJob:
    return RawJob(
        title="Cloud Engineer",
        company="Acme",
        location="Remote",
        url="https://example.com/job",
        source=source,
        h1b_sponsor_verified=verified,
    )


class TestIsDroppableSource:
    def test_linkedin_is_droppable(self):
        assert is_droppable_source("linkedin") is True

    def test_indeed_is_droppable(self):
        assert is_droppable_source("indeed") is True

    def test_google_is_droppable(self):
        assert is_droppable_source("google") is True

    def test_workday_is_droppable(self):
        assert is_droppable_source("workday") is True

    def test_hackernews_is_not_droppable(self):
        assert is_droppable_source("hackernews") is False

    def test_remoteok_is_not_droppable(self):
        assert is_droppable_source("remoteok") is False

    def test_greenhouse_prefixed_is_not_droppable(self):
        assert is_droppable_source("greenhouse-anthropic") is False

    def test_lever_prefixed_is_not_droppable(self):
        assert is_droppable_source("lever-stripe") is False

    def test_ashby_prefixed_is_not_droppable(self):
        assert is_droppable_source("ashby-foo") is False

    def test_unknown_source_is_not_droppable(self):
        # Conservative default: don't drop sources we don't recognize
        assert is_droppable_source("some-new-source") is False


class TestPartitionDrops:
    def test_verified_false_from_droppable_source_is_dropped(self):
        jobs = [_job("linkedin", False)]
        kept, dropped = partition_drops(jobs)
        assert kept == []
        assert dropped == jobs

    def test_verified_false_from_keep_source_is_kept(self):
        jobs = [
            _job("hackernews", False),
            _job("remoteok", False),
            _job("greenhouse-anthropic", False),
            _job("lever-stripe", False),
            _job("ashby-foo", False),
        ]
        kept, dropped = partition_drops(jobs)
        assert kept == jobs
        assert dropped == []

    def test_verified_true_is_kept_from_any_source(self):
        jobs = [
            _job("linkedin", True),
            _job("indeed", True),
            _job("hackernews", True),
            _job("greenhouse-foo", True),
        ]
        kept, dropped = partition_drops(jobs)
        assert kept == jobs
        assert dropped == []

    def test_verified_none_is_kept_from_any_source(self):
        jobs = [
            _job("linkedin", None),
            _job("indeed", None),
            _job("greenhouse-foo", None),
        ]
        kept, dropped = partition_drops(jobs)
        assert kept == jobs
        assert dropped == []

    def test_mixed_batch(self):
        keep_a = _job("linkedin", True)
        drop_a = _job("indeed", False)
        keep_b = _job("hackernews", False)  # kept despite False because source
        keep_c = _job("greenhouse-x", None)
        drop_b = _job("workday", False)

        kept, dropped = partition_drops([keep_a, drop_a, keep_b, keep_c, drop_b])
        assert kept == [keep_a, keep_b, keep_c]
        assert dropped == [drop_a, drop_b]

    def test_empty_input(self):
        kept, dropped = partition_drops([])
        assert kept == []
        assert dropped == []
