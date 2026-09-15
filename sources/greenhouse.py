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

from config import EXCLUDE_TITLE_KEYWORDS, TITLE_DOMAIN_KEYWORDS
from models.job import RawJob
from sources._dates import parse_iso
from sources.base import SourceAdapter, SourceResult, scrape_boards

logger = logging.getLogger(__name__)

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards"


def _title_is_relevant(title: str) -> bool:
    """Check whether a title is worth pulling from a board-style ATS.

    Shared by the Greenhouse, Lever and Ashby adapters, all of which return a
    company's entire board and have to filter client-side.

    Applies BOTH halves of Stage 1's title gate — the domain allow-list and the
    exclusion list. Skipping exclusions here let "Senior ...", "... Intern" and
    industrial titles ("Automation Technician") into the pipeline just to be
    rejected a phase later.
    """
    title_lower = title.lower()
    if any(kw in title_lower for kw in EXCLUDE_TITLE_KEYWORDS):
        return False
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
        total_raw = 0

        async def one(session, company) -> list[RawJob]:
            nonlocal total_raw
            raw_count, company_jobs = await self._scrape_company(
                session, company["token"], company["name"]
            )
            total_raw += raw_count
            return company_jobs

        result = await scrape_boards(self.companies, one, label="Greenhouse")
        logger.info(
            f"Greenhouse: {len(result.jobs)} relevant jobs from {total_raw} total "
            f"across {len(self.companies)} companies"
        )
        return result

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
                    posted_at=parse_iso(item.get("created_at") or item.get("updated_at")),
                )
            )

        return len(raw_items), jobs
