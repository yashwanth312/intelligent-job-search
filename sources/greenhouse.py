"""Greenhouse Job Board API adapter — no auth required."""
from __future__ import annotations

import logging
from datetime import datetime

import aiohttp
from bs4 import BeautifulSoup

from models.job import RawJob
from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseAdapter(SourceAdapter):
    name = "greenhouse"

    def __init__(self, companies: list[dict]):
        """companies: list of {"token": "anthropic", "name": "Anthropic"}"""
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
                    msg = f"Greenhouse {company['name']}: {e}"
                    logger.warning(msg)
                    errors.append(msg)

        logger.info(f"Greenhouse: scraped {len(jobs)} jobs from {len(self.companies)} companies")
        return SourceResult(jobs=jobs, errors=errors)

    async def _scrape_company(
        self, session: aiohttp.ClientSession, token: str, name: str
    ) -> list[RawJob]:
        url = f"{GREENHOUSE_API}/{token}/jobs?content=true"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                logger.warning(f"Greenhouse {name}: HTTP {resp.status}")
                return []
            data = await resp.json()

        jobs: list[RawJob] = []
        for item in data.get("jobs", []):
            description_html = item.get("content", "")
            description = BeautifulSoup(description_html, "html.parser").get_text(
                separator="\n", strip=True
            ) if description_html else None

            location_name = ""
            loc = item.get("location")
            if isinstance(loc, dict):
                location_name = loc.get("name", "")
            elif isinstance(loc, str):
                location_name = loc

            jobs.append(
                RawJob(
                    title=item.get("title", ""),
                    company=name,
                    location=location_name,
                    description=description,
                    url=item.get("absolute_url", ""),
                    source=f"greenhouse-{token}",
                )
            )

        return jobs
