import pytest
from unittest.mock import AsyncMock, MagicMock
from sources.ashby import AshbyAdapter
from tests.test_greenhouse import AsyncContextManager


MOCK_ASHBY_RESPONSE = {
    "jobs": [
        {
            "title": "Security Engineer",
            "location": "Remote, US",
            "descriptionPlain": "Security role with AWS",
            "jobUrl": "https://jobs.ashbyhq.com/testco/123",
        },
    ]
}


class TestAshbyAdapter:
    @pytest.mark.asyncio
    async def test_scrape_returns_jobs(self):
        adapter = AshbyAdapter(companies=[{"token": "testco", "name": "TestCo"}])

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=MOCK_ASHBY_RESPONSE)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncContextManager(mock_response))

        result = await adapter._scrape_company(mock_session, "testco", "TestCo")
        assert len(result) == 1
        assert result[0].title == "Security Engineer"
        assert result[0].source == "ashby-testco"
