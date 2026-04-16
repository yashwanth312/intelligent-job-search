"""Ashby Job Board API adapter — no auth required.

Ashby APIs return ALL jobs for a company. This adapter filters
results to only return jobs with relevant titles.
"""
from __future__ import annotations

import logging

import aiohttp

from models.job import RawJob
from sources.base import SourceAdapter, SourceResult
from sources.greenhouse import _title_is_relevant

logger = logging.getLogger(__name__)

ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board"


class AshbyAdapter(SourceAdapter):
    name = "ashby"

    def __init__(self, companies: list[dict]):
        self.companies = companies

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        jobs: list[RawJob] = []
        errors: list[str] = []

        async with aiohttp.ClientSession() as session:
            for company in self.companies:
                try:
                    company_jobs = await self._scrape_company(
                        session, company["token"], company["name"]
                    )
                    jobs.extend(company_jobs)
                except Exception as e:
                    msg = f"Ashby {company['name']}: {e}"
                    logger.warning(msg)
                    errors.append(msg)

        logger.info(f"Ashby: scraped {len(jobs)} relevant jobs from {len(self.companies)} companies")
        return SourceResult(jobs=jobs, errors=errors)

    async def _scrape_company(
        self, session: aiohttp.ClientSession, token: str, name: str
    ) -> list[RawJob]:
        url = f"{ASHBY_API}/{token}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                logger.warning(f"Ashby {name}: HTTP {resp.status}")
                return []
            data = await resp.json()

        jobs: list[RawJob] = []
        for item in data.get("jobs", []):
            title = item.get("title", "")
            if not _title_is_relevant(title):
                continue

            location = item.get("location", "")
            if isinstance(location, dict):
                location = location.get("name", "")

            jobs.append(
                RawJob(
                    title=title,
                    company=name,
                    location=location,
                    description=item.get("descriptionPlain", item.get("description", "")),
                    url=item.get("jobUrl", item.get("applyUrl", "")),
                    source=f"ashby-{token}",
                )
            )

        return jobs
