"""Greenhouse Job Board API adapter — no auth required.

Greenhouse APIs return ALL jobs for a company (no title search).
This adapter filters results to only return jobs whose titles
match the target domain keywords, so we don't flood the pipeline
with sales/marketing/legal roles.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

import aiohttp
from bs4 import BeautifulSoup

from config import TITLE_DOMAIN_KEYWORDS
from models.job import RawJob
from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards"


def _title_is_relevant(title: str) -> bool:
    """Check if a job title matches any of our domain keywords."""
    title_lower = title.lower()
    return any(
        re.search(r'\b' + re.escape(kw) + r'\b', title_lower)
        for kw in TITLE_DOMAIN_KEYWORDS
    )


class GreenhouseAdapter(SourceAdapter):
    name = "greenhouse"

    def __init__(self, companies: list[dict]):
        """companies: list of {"token": "anthropic", "name": "Anthropic"}"""
        self.companies = companies

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        jobs: list[RawJob] = []
        errors: list[str] = []
        total_raw = 0

        async with aiohttp.ClientSession() as session:
            for company in self.companies:
                try:
                    company_jobs = await self._scrape_company(
                        session, company["token"], company["name"]
                    )
                    total_raw += company_jobs[0]
                    jobs.extend(company_jobs[1])
                except Exception as e:
                    msg = f"Greenhouse {company['name']}: {e}"
                    logger.warning(msg)
                    errors.append(msg)

        logger.info(
            f"Greenhouse: {len(jobs)} relevant jobs from {total_raw} total "
            f"across {len(self.companies)} companies"
        )
        return SourceResult(jobs=jobs, errors=errors)

    async def _scrape_company(
        self, session: aiohttp.ClientSession, token: str, name: str
    ) -> tuple[int, list[RawJob]]:
        url = f"{GREENHOUSE_API}/{token}/jobs?content=true"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                logger.warning(f"Greenhouse {name}: HTTP {resp.status}")
                return 0, []
            data = await resp.json()

        raw_items = data.get("jobs", [])
        jobs: list[RawJob] = []
        for item in raw_items:
            title = item.get("title", "")

            # Only keep jobs with relevant titles
            if not _title_is_relevant(title):
                continue

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
                    title=title,
                    company=name,
                    location=location_name,
                    description=description,
                    url=item.get("absolute_url", ""),
                    source=f"greenhouse-{token}",
                )
            )

        return len(raw_items), jobs
