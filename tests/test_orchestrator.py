from datetime import datetime, timedelta, timezone

import pytest
from sources.orchestrator import ScraperOrchestrator, filter_fresh_jobs
from sources.base import SourceAdapter, SourceResult
from models.job import RawJob


class FakeSource(SourceAdapter):
    def __init__(self, name_: str, jobs_: list[RawJob]):
        self.name = name_
        self._jobs = jobs_

    async def scrape(self, titles, locations):
        return SourceResult(jobs=self._jobs, errors=[])


class FailingSource(SourceAdapter):
    name = "failing"

    async def scrape(self, titles, locations):
        raise ConnectionError("Source is down")


class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_scrape_all_sources_in_parallel(self):
        source_a = FakeSource("source_a", [
            RawJob(title="Job1", company="Co1", location="NYC",
                   url="https://a.com/1", source="source_a"),
        ])
        source_b = FakeSource("source_b", [
            RawJob(title="Job2", company="Co2", location="SF",
                   url="https://b.com/1", source="source_b"),
        ])

        orchestrator = ScraperOrchestrator(adapters=[source_a, source_b])
        result = await orchestrator.scrape_all(["Cloud Engineer"], ["Remote"])
        assert len(result.jobs) == 2
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_dedup_by_fingerprint(self):
        job = RawJob(title="Cloud Eng", company="Google", location="Remote",
                     url="https://a.com", source="source_a")
        source_a = FakeSource("source_a", [job])
        source_b = FakeSource("source_b", [
            RawJob(title="Cloud Eng", company="Google", location="Remote",
                   url="https://b.com", source="source_b"),
        ])

        orchestrator = ScraperOrchestrator(adapters=[source_a, source_b])
        result = await orchestrator.scrape_all(["Cloud Eng"], ["Remote"])
        assert len(result.jobs) == 1  # deduped

    @pytest.mark.asyncio
    async def test_one_source_failure_doesnt_kill_pipeline(self):
        good = FakeSource("good", [
            RawJob(title="Job1", company="Co1", location="NYC",
                   url="https://a.com", source="good"),
        ])
        bad = FailingSource()

        orchestrator = ScraperOrchestrator(adapters=[good, bad])
        result = await orchestrator.scrape_all(["Job"], ["NYC"])
        assert len(result.jobs) == 1
        assert len(result.errors) == 1
        assert "Source is down" in result.errors[0]


class TestFilterFreshJobs:
    def _job(self, source: str, posted_at=None) -> RawJob:
        return RawJob(
            title="Cloud Engineer", company="Co", location="Remote",
            url="https://x.com", source=source, posted_at=posted_at,
        )

    def test_keeps_recent_posted_at(self):
        now = datetime.now(timezone.utc)
        fresh_job = self._job("greenhouse-x", posted_at=now - timedelta(hours=2))
        stale_job = self._job("greenhouse-x", posted_at=now - timedelta(hours=48))
        fresh, stale = filter_fresh_jobs([fresh_job, stale_job], hours_old=24)
        assert fresh == [fresh_job]
        assert stale == [stale_job]

    def test_drops_unknown_posted_at_for_untrusted_source(self):
        # A source that doesn't pre-filter by age AND has no posted_at
        # must be dropped — we can't prove it's new.
        job = self._job("hackernews", posted_at=None)
        fresh, stale = filter_fresh_jobs([job], hours_old=24)
        assert fresh == []
        assert stale == [job]

    def test_keeps_unknown_posted_at_for_jobspy_sources(self):
        # JobSpy passes hours_old=24 at scrape time, so we trust the source
        # when posted_at happens to be missing from an individual row.
        li = self._job("linkedin", posted_at=None)
        ind = self._job("indeed", posted_at=None)
        gg = self._job("google", posted_at=None)
        fresh, stale = filter_fresh_jobs([li, ind, gg], hours_old=24)
        assert len(fresh) == 3
        assert stale == []

    def test_boundary_exactly_at_cutoff(self):
        # A job posted exactly at the cutoff should be kept (>= cutoff).
        now = datetime.now(timezone.utc)
        edge = self._job("greenhouse-x", posted_at=now - timedelta(hours=24, seconds=-1))
        fresh, stale = filter_fresh_jobs([edge], hours_old=24)
        assert fresh == [edge]
