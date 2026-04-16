import pytest
from unittest.mock import AsyncMock, MagicMock
from sources.greenhouse import GreenhouseAdapter


MOCK_GREENHOUSE_RESPONSE = {
    "jobs": [
        {
            "id": 123,
            "title": "Cloud Engineer",
            "location": {"name": "San Francisco, CA"},
            "content": "<p>We need a Cloud Engineer with AWS experience.</p>",
            "absolute_url": "https://boards.greenhouse.io/testco/jobs/123",
            "updated_at": "2026-04-15T10:00:00Z",
            "metadata": [],
        },
        {
            "id": 456,
            "title": "Senior Staff Engineer",
            "location": {"name": "Remote"},
            "content": "<p>10+ years experience required.</p>",
            "absolute_url": "https://boards.greenhouse.io/testco/jobs/456",
            "updated_at": "2026-04-15T10:00:00Z",
            "metadata": [],
        },
    ]
}


class AsyncContextManager:
    """Helper to mock async context managers."""
    def __init__(self, return_value):
        self.return_value = return_value
    async def __aenter__(self):
        return self.return_value
    async def __aexit__(self, *args):
        pass


class TestGreenhouseAdapter:
    @pytest.mark.asyncio
    async def test_scrape_returns_only_relevant_jobs(self):
        adapter = GreenhouseAdapter(
            companies=[{"token": "testco", "name": "TestCo"}]
        )

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=MOCK_GREENHOUSE_RESPONSE)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncContextManager(mock_response))

        total_raw, jobs = await adapter._scrape_company(mock_session, "testco", "TestCo")
        assert total_raw == 2  # 2 jobs in response
        assert len(jobs) == 1  # Only "Cloud Engineer" passes title filter
        assert jobs[0].company == "TestCo"
        assert jobs[0].source == "greenhouse-testco"
        assert jobs[0].title == "Cloud Engineer"

    @pytest.mark.asyncio
    async def test_handles_404_gracefully(self):
        adapter = GreenhouseAdapter(
            companies=[{"token": "nonexistent", "name": "Gone"}]
        )

        mock_response = AsyncMock()
        mock_response.status = 404

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncContextManager(mock_response))

        total_raw, jobs = await adapter._scrape_company(mock_session, "nonexistent", "Gone")
        assert total_raw == 0
        assert len(jobs) == 0
