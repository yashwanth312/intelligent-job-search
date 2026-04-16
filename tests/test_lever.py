import pytest
from unittest.mock import AsyncMock, MagicMock
from sources.lever import LeverAdapter
from tests.test_greenhouse import AsyncContextManager


MOCK_LEVER_RESPONSE = [
    {
        "id": "abc123",
        "text": "DevOps Engineer",
        "categories": {"location": "New York, NY", "team": "Infrastructure"},
        "descriptionPlain": "We need a DevOps engineer with K8s experience.",
        "hostedUrl": "https://jobs.lever.co/testco/abc123",
        "createdAt": 1713200000000,
    },
]


class TestLeverAdapter:
    @pytest.mark.asyncio
    async def test_scrape_returns_jobs(self):
        adapter = LeverAdapter(companies=[{"token": "testco", "name": "TestCo"}])

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=MOCK_LEVER_RESPONSE)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncContextManager(mock_response))

        result = await adapter._scrape_company(mock_session, "testco", "TestCo")
        assert len(result) == 1
        assert result[0].title == "DevOps Engineer"
        assert result[0].source == "lever-testco"
