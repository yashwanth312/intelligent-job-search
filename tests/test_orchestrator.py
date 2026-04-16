import pytest
from sources.orchestrator import ScraperOrchestrator
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
