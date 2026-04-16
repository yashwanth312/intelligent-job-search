import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from sources.linkedin_indeed import LinkedInIndeedAdapter


MOCK_DF = pd.DataFrame([
    {
        "title": "Cloud Engineer",
        "company": "Google",
        "location": "Remote",
        "description": "Cloud role with AWS",
        "job_url": "https://linkedin.com/jobs/123",
        "min_amount": 120000,
        "max_amount": 180000,
        "site": "linkedin",
    }
])


class TestLinkedInIndeedAdapter:
    @pytest.mark.asyncio
    async def test_scrape_converts_dataframe_to_raw_jobs(self):
        adapter = LinkedInIndeedAdapter(sites=["linkedin"])

        with patch("jobspy.scrape_jobs", return_value=MOCK_DF):
            result = await adapter.scrape(["Cloud Engineer"], ["Remote"])

        assert len(result.jobs) == 1
        assert result.jobs[0].title == "Cloud Engineer"
        assert result.jobs[0].source == "linkedin"
        assert result.jobs[0].salary_min == 120000
