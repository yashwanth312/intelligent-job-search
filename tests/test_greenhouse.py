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
    async def test_scrape_returns_jobs(self):
        adapter = GreenhouseAdapter(
            companies=[{"token": "testco", "name": "TestCo"}]
        )

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=MOCK_GREENHOUSE_RESPONSE)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncContextManager(mock_response))

        result = await adapter._scrape_company(mock_session, "testco", "TestCo")
        assert len(result) == 2
        assert result[0].company == "TestCo"
        assert result[0].source == "greenhouse-testco"
        assert "Cloud Engineer" in [j.title for j in result]

    @pytest.mark.asyncio
    async def test_handles_404_gracefully(self):
        adapter = GreenhouseAdapter(
            companies=[{"token": "nonexistent", "name": "Gone"}]
        )

        mock_response = AsyncMock()
        mock_response.status = 404

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncContextManager(mock_response))

        result = await adapter._scrape_company(mock_session, "nonexistent", "Gone")
        assert len(result) == 0
