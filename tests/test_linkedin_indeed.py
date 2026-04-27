import pytest
import threading
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


MOCK_DF_WITH_WORKDAY = pd.DataFrame([
    {
        "title": "Cloud Engineer",
        "company": "Microsoft",
        "location": "Redmond, WA",
        "description": "Cloud role with Azure",
        "job_url": "https://linkedin.com/jobs/123",
        "job_url_direct": "https://microsoft.wd5.myworkdayjobs.com/en-US/External_Careers/job/CE_JR1",
        "min_amount": None,
        "max_amount": None,
        "site": "linkedin",
        "date_posted": None,
    }
])


class TestWorkdayDiscovery:
    def test_scrape_one_discovers_workday_tenant(self):
        adapter = LinkedInIndeedAdapter(sites=["linkedin"])

        with patch("jobspy.scrape_jobs", return_value=MOCK_DF_WITH_WORKDAY):
            adapter._scrape_one("linkedin", "Cloud Engineer", "Seattle, WA")

        companies = adapter.discovered_workday_companies
        assert len(companies) == 1
        assert companies[0]["tenant"] == "microsoft"
        assert companies[0]["wd_server"] == "wd5"
        assert companies[0]["name"] == "Microsoft"

    def test_discovered_companies_deduplicates_across_calls(self):
        adapter = LinkedInIndeedAdapter(sites=["linkedin"])

        with patch("jobspy.scrape_jobs", return_value=MOCK_DF_WITH_WORKDAY):
            adapter._scrape_one("linkedin", "Cloud Engineer", "Seattle, WA")
            adapter._scrape_one("linkedin", "DevOps Engineer", "Seattle, WA")

        assert len(adapter.discovered_workday_companies) == 1

    def test_non_workday_urls_not_collected(self):
        adapter = LinkedInIndeedAdapter(sites=["linkedin"])
        df_no_workday = pd.DataFrame([{
            "title": "Cloud Engineer",
            "company": "Google",
            "location": "Remote",
            "description": "Cloud role",
            "job_url": "https://linkedin.com/jobs/999",
            "job_url_direct": "https://careers.google.com/jobs/results/123",
            "min_amount": None,
            "max_amount": None,
            "site": "linkedin",
            "date_posted": None,
        }])

        with patch("jobspy.scrape_jobs", return_value=df_no_workday):
            adapter._scrape_one("linkedin", "Cloud Engineer", "Remote")

        assert adapter.discovered_workday_companies == []
