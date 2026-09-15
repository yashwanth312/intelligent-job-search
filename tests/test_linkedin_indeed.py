import pytest
import threading
import pandas as pd
from unittest.mock import patch, MagicMock
from sources.linkedin_indeed import LinkedInIndeedAdapter
from models.job import RawJob


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

        with patch("jobspy.scrape_jobs", return_value=MOCK_DF), \
             patch("sources.linkedin_indeed._linkedin_bucket.acquire"):
            result = await adapter.scrape(["Cloud Engineer"], ["Remote"])

        assert len(result.jobs) == 1
        assert result.jobs[0].title == "Cloud Engineer"
        assert result.jobs[0].source == "linkedin"
        assert result.jobs[0].salary_min == 120000

    def test_linkedin_fetch_description_always_false_at_scrape_time(self):
        """Descriptions are deferred to fetch_descriptions() post-title-gate —
        scrape_jobs() must never be asked to fetch them inline."""
        adapter = LinkedInIndeedAdapter(sites=["linkedin"])

        with patch("jobspy.scrape_jobs", return_value=MOCK_DF) as mock_scrape, \
             patch("sources.linkedin_indeed._linkedin_bucket.acquire"):
            adapter._scrape_one("linkedin", "Cloud Engineer", "Seattle, WA")

        assert mock_scrape.call_args.kwargs["linkedin_fetch_description"] is False


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

        with patch("jobspy.scrape_jobs", return_value=MOCK_DF_WITH_WORKDAY), \
             patch("sources.linkedin_indeed._linkedin_bucket.acquire"):
            adapter._scrape_one("linkedin", "Cloud Engineer", "Seattle, WA")

        companies = adapter.discovered_workday_companies
        assert len(companies) == 1
        assert companies[0]["tenant"] == "microsoft"
        assert companies[0]["wd_server"] == "wd5"
        assert companies[0]["name"] == "Microsoft"

    def test_discovered_companies_deduplicates_across_calls(self):
        adapter = LinkedInIndeedAdapter(sites=["linkedin"])

        with patch("jobspy.scrape_jobs", return_value=MOCK_DF_WITH_WORKDAY), \
             patch("sources.linkedin_indeed._linkedin_bucket.acquire"):
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

        with patch("jobspy.scrape_jobs", return_value=df_no_workday), \
             patch("sources.linkedin_indeed._linkedin_bucket.acquire"):
            adapter._scrape_one("linkedin", "Cloud Engineer", "Remote")

        assert adapter.discovered_workday_companies == []


class TestFetchDescriptions:
    def _job(self, url="https://www.linkedin.com/jobs/view/123456", description=None,
             source="linkedin", company="Acme"):
        return RawJob(
            title="Cloud Engineer", company=company, location="Remote",
            url=url, source=source, description=description,
        )

    @pytest.mark.asyncio
    async def test_skips_jobs_that_already_have_a_description(self):
        adapter = LinkedInIndeedAdapter()
        job = self._job(description="already have this")

        with patch("jobspy.linkedin.LinkedIn") as mock_cls:
            n = await adapter.fetch_descriptions([job])

        assert n == 0
        mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_non_linkedin_sources(self):
        adapter = LinkedInIndeedAdapter()
        job = self._job(source="indeed")

        with patch("jobspy.linkedin.LinkedIn") as mock_cls:
            n = await adapter.fetch_descriptions([job])

        assert n == 0
        mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_fills_description_via_get_job_details(self):
        adapter = LinkedInIndeedAdapter()
        job = self._job()

        mock_instance = MagicMock()
        mock_instance._get_job_details.return_value = {
            "description": "**Markdown** description", "job_url_direct": None,
        }
        with patch("jobspy.linkedin.LinkedIn", return_value=mock_instance), \
             patch("sources.linkedin_indeed._linkedin_bucket.acquire"):
            n = await adapter.fetch_descriptions([job])

        assert n == 1
        assert job.description == "**Markdown** description"
        mock_instance._get_job_details.assert_called_once_with("123456")

    @pytest.mark.asyncio
    async def test_discovers_workday_tenant_from_job_url_direct(self):
        adapter = LinkedInIndeedAdapter()
        job = self._job(company="Microsoft")

        mock_instance = MagicMock()
        mock_instance._get_job_details.return_value = {
            "description": "desc",
            "job_url_direct": "https://microsoft.wd5.myworkdayjobs.com/en-US/External_Careers/job/CE_JR1",
        }
        with patch("jobspy.linkedin.LinkedIn", return_value=mock_instance), \
             patch("sources.linkedin_indeed._linkedin_bucket.acquire"):
            await adapter.fetch_descriptions([job])

        companies = adapter.discovered_workday_companies
        assert len(companies) == 1
        assert companies[0]["tenant"] == "microsoft"

    @pytest.mark.asyncio
    async def test_malformed_url_skipped_gracefully(self):
        adapter = LinkedInIndeedAdapter()
        job = self._job(url="https://not-a-real-linkedin-url.example.com/")

        with patch("jobspy.linkedin.LinkedIn") as mock_cls:
            n = await adapter.fetch_descriptions([job])

        assert n == 0
        assert job.description is None

    @pytest.mark.asyncio
    async def test_failed_fetch_does_not_raise(self):
        adapter = LinkedInIndeedAdapter()
        job = self._job()

        mock_instance = MagicMock()
        mock_instance._get_job_details.side_effect = RuntimeError("network error")
        with patch("jobspy.linkedin.LinkedIn", return_value=mock_instance), \
             patch("sources.linkedin_indeed._linkedin_bucket.acquire"):
            n = await adapter.fetch_descriptions([job])

        assert n == 0
        assert job.description is None

    @pytest.mark.asyncio
    async def test_progress_callback_fires_once_per_target(self):
        adapter = LinkedInIndeedAdapter()
        jobs = [self._job(url=f"https://www.linkedin.com/jobs/view/{i}") for i in range(3)]
        calls = []

        mock_instance = MagicMock()
        mock_instance._get_job_details.return_value = {"description": "d", "job_url_direct": None}
        with patch("jobspy.linkedin.LinkedIn", return_value=mock_instance), \
             patch("sources.linkedin_indeed._linkedin_bucket.acquire"):
            await adapter.fetch_descriptions(jobs, on_progress=lambda n: calls.append(n))

        assert len(calls) == 3
