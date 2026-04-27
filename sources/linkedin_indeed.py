"""LinkedIn + Indeed adapter via python-jobspy library."""
from __future__ import annotations

import asyncio
import datetime as dt_mod
import logging
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from config import HOURS_OLD, RESULTS_PER_SEARCH
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


def _safe_date(val) -> datetime | None:
    """Coerce whatever JobSpy returns for date_posted to a tz-aware UTC datetime."""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, dt_mod.date):
        return datetime(val.year, val.month, val.day, tzinfo=timezone.utc)
    try:
        s = str(val).strip().replace("Z", "+00:00")
        if not s or s.lower() == "nan":
            return None
        parsed = datetime.fromisoformat(s)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


class LinkedInIndeedAdapter(SourceAdapter):
    name = "linkedin_indeed"

    def __init__(
        self,
        sites: list[str] | None = None,
        results_per_search: int | None = None,
        hours_old: int | None = None,
    ):
        # ZipRecruiter removed 2026-04-24: Cloudflare WAF blocks JobSpy's
        # hardcoded mobile-app credentials with 403 forbidden. JobSpy swallows
        # the 403 and silently returns empty, wasting ~71s/run on dead calls.
        # Re-add "zip_recruiter" here if upstream JobSpy fixes its auth.
        self.sites = sites or ["linkedin", "indeed", "google"]
        self.results_per_search = results_per_search if results_per_search is not None else RESULTS_PER_SEARCH
        self.hours_old = hours_old if hours_old is not None else HOURS_OLD
        self._discovered: dict[str, dict] = {}
        self._lock = threading.Lock()

    @property
    def discovered_workday_companies(self) -> list[dict]:
        with self._lock:
            return list(self._discovered.values())

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        """Scrape LinkedIn/Indeed using TARGET_TITLES x locations.

        Each title is searched as-is so niche titles like "AI Security Engineer"
        get their own dedicated search rather than competing with broader terms.
        Locations containing "remote" are translated to United States + is_remote=True
        so results are scoped to US-based remote roles, not global ones.
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

        is_remote = location.strip().lower() == "remote"
        resolved_location = "United States" if is_remote else location

        try:
            df = scrape_jobs(
                site_name=[site],
                search_term=title,
                location=resolved_location,
                results_wanted=self.results_per_search,
                hours_old=self.hours_old,
                is_remote=is_remote,
                country_indeed="usa",
                enforce_annual_salary=True,
            )
        except Exception as e:
            logger.warning(f"{site} scrape failed for '{title}' in '{location}': {e}")
            return []

        jobs: list[RawJob] = []
        for _, row in df.iterrows():
            raw_title = _safe_str(row.get("title"))
            raw_company = _safe_str(row.get("company"))
            # Passively discover Workday tenants from direct application URLs
            direct_url = _safe_str(row.get("job_url_direct"))
            if direct_url and "myworkdayjobs.com" in direct_url and raw_company:
                from sources.workday_discovery import extract_workday_tenant
                discovery = extract_workday_tenant(direct_url, raw_company)
                if discovery:
                    with self._lock:
                        self._discovered.setdefault(discovery["tenant"], discovery)
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
                    posted_at=_safe_date(row.get("date_posted")),
                )
            )

        return jobs
