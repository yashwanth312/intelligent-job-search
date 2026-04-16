import pytest
from sources.base import SourceAdapter, SourceResult
from models.job import RawJob


class MockAdapter(SourceAdapter):
    name = "mock"

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        jobs = [
            RawJob(
                title="Cloud Engineer", company="TestCo", location="Remote",
                description="A cloud job", url="https://test.com/1", source="mock",
            )
        ]
        return SourceResult(jobs=jobs, errors=[])


class TestSourceAdapter:
    @pytest.mark.asyncio
    async def test_mock_adapter_returns_jobs(self):
        adapter = MockAdapter()
        result = await adapter.scrape(["Cloud Engineer"], ["Remote"])
        assert len(result.jobs) == 1
        assert result.jobs[0].source == "mock"
        assert len(result.errors) == 0

    def test_adapter_has_name(self):
        adapter = MockAdapter()
        assert adapter.name == "mock"
