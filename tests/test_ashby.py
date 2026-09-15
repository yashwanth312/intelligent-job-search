import pytest
from unittest.mock import AsyncMock, MagicMock
from sources.ashby import AshbyAdapter
from tests.test_greenhouse import AsyncContextManager


MOCK_ASHBY_RESPONSE = {
    "jobs": [
        {
            "title": "Cloud Infrastructure Engineer",
            "location": "Remote, US",
            "descriptionPlain": "Infrastructure role with AWS",
            "jobUrl": "https://jobs.ashbyhq.com/testco/123",
        },
    ]
}

# A bare security title no longer carries an infra keyword, so the adapter's
# title-domain filter drops it before it reaches the pipeline.
MOCK_ASHBY_OFF_DOMAIN = {
    "jobs": [
        {
            "title": "Security Analyst",
            "location": "Remote, US",
            "descriptionPlain": "SOC monitoring role",
            "jobUrl": "https://jobs.ashbyhq.com/testco/456",
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
        assert result[0].title == "Cloud Infrastructure Engineer"
        assert result[0].source == "ashby-testco"

    @pytest.mark.asyncio
    async def test_off_domain_titles_are_filtered_out(self):
        adapter = AshbyAdapter(companies=[{"token": "testco", "name": "TestCo"}])

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=MOCK_ASHBY_OFF_DOMAIN)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncContextManager(mock_response))

        result = await adapter._scrape_company(mock_session, "testco", "TestCo")
        assert result == []
