"""Lever public postings API adapter — no auth required."""
from __future__ import annotations

import logging
from datetime import datetime

import aiohttp

from models.job import RawJob
from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)

LEVER_API = "https://api.lever.co/v0/postings"


class LeverAdapter(SourceAdapter):
    name = "lever"

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
                    msg = f"Lever {company['name']}: {e}"
                    logger.warning(msg)
                    errors.append(msg)

        logger.info(f"Lever: scraped {len(jobs)} jobs from {len(self.companies)} companies")
        return SourceResult(jobs=jobs, errors=errors)

    async def _scrape_company(
        self, session: aiohttp.ClientSession, token: str, name: str
    ) -> list[RawJob]:
        url = f"{LEVER_API}/{token}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                logger.warning(f"Lever {name}: HTTP {resp.status}")
                return []
            data = await resp.json()

        if not isinstance(data, list):
            return []

        jobs: list[RawJob] = []
        for item in data:
            location = ""
            categories = item.get("categories", {})
            if isinstance(categories, dict):
                location = categories.get("location", "")

            jobs.append(
                RawJob(
                    title=item.get("text", ""),
                    company=name,
                    location=location,
                    description=item.get("descriptionPlain", ""),
                    url=item.get("hostedUrl", ""),
                    source=f"lever-{token}",
                )
            )

        return jobs
