import pytest
from unittest.mock import AsyncMock, MagicMock
from sources.remoteok import RemoteOKAdapter
from tests.test_greenhouse import AsyncContextManager


MOCK_REMOTEOK_RESPONSE = [
    {"legal": "terms"},  # First item is always metadata
    {
        "id": "123",
        "company": "TestCo",
        "position": "DevOps Engineer",
        "location": "Worldwide",
        "description": "Remote DevOps role with K8s",
        "url": "https://remoteok.com/jobs/123",
        "salary_min": 100000,
        "salary_max": 150000,
    },
]


class TestRemoteOKAdapter:
    @pytest.mark.asyncio
    async def test_scrape_returns_jobs(self):
        adapter = RemoteOKAdapter()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=MOCK_REMOTEOK_RESPONSE)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncContextManager(mock_response))

        result = await adapter._fetch_jobs(mock_session)
        assert len(result) == 1
        assert result[0].title == "DevOps Engineer"
        assert result[0].source == "remoteok"
