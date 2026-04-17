"""LinkedIn + Indeed adapter via python-jobspy library."""
from __future__ import annotations

import asyncio
import logging
import math
from concurrent.futures import ThreadPoolExecutor

from models.job import RawJob
from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)


def _safe_str(val) -> str | None:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    return str(val).strip() or None


def _safe_int(val) -> int | None:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


class LinkedInIndeedAdapter(SourceAdapter):
    name = "linkedin_indeed"

    def __init__(self, sites: list[str] | None = None, results_per_search: int = 25, hours_old: int = 24):
        self.sites = sites or ["linkedin", "indeed", "glassdoor", "zip_recruiter", "google"]
        self.results_per_search = results_per_search
        self.hours_old = hours_old

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        """Scrape LinkedIn/Indeed using search queries x locations.

        `titles` here should be SEARCH_QUERIES (grouped broad terms),
        not the full TARGET_TITLES list. Each query is searched across
        all locations on all sites.
        """
        jobs: list[RawJob] = []
        errors: list[str] = []

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=8) as pool:
            tasks = []
            for site in self.sites:
                for title in titles:
                    for location in locations:
                        tasks.append(
                            loop.run_in_executor(
                                pool, self._scrape_one, site, title, location
                            )
                        )

            results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                errors.append(str(result))
            elif isinstance(result, list):
                jobs.extend(result)

        logger.info(f"LinkedIn/Indeed: scraped {len(jobs)} jobs")
        return SourceResult(jobs=jobs, errors=errors)

    def _scrape_one(self, site: str, title: str, location: str) -> list[RawJob]:
        from jobspy import scrape_jobs

        try:
            df = scrape_jobs(
                site_name=[site],
                search_term=title,
                location=location,
                results_wanted=self.results_per_search,
                hours_old=self.hours_old,
            )
        except Exception as e:
            logger.warning(f"{site} scrape failed for '{title}' in '{location}': {e}")
            return []

        jobs: list[RawJob] = []
        for _, row in df.iterrows():
            raw_title = _safe_str(row.get("title"))
            raw_company = _safe_str(row.get("company"))
            if not raw_title or not raw_company:
                continue

            jobs.append(
                RawJob(
                    title=raw_title,
                    company=raw_company,
                    location=_safe_str(row.get("location")) or location,
                    description=_safe_str(row.get("description")),
                    salary_min=_safe_int(row.get("min_amount")),
                    salary_max=_safe_int(row.get("max_amount")),
                    url=_safe_str(row.get("job_url")) or "",
                    source=site,
                )
            )

        return jobs
