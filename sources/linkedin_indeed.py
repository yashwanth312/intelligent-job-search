"""LinkedIn + Indeed + Google adapter via python-jobspy.

Per-site execution model
------------------------
Each site (linkedin, indeed, google) runs in its OWN thread pool with its
OWN concurrency cap, all three pools running concurrently. LinkedIn rate-
limits aggressively, so it gets a single worker gated by a shared token
bucket; Indeed and Google tolerate parallelism so they get more workers. A
LinkedIn 429 storm therefore can no longer starve Indeed/Google.

Accumulator pattern
-------------------
Each completed (site, title, location) appends its rows to a shared
lock-protected buffer immediately. `scrape()` returns whatever is in the
buffer at the end — even if the run is cancelled mid-flight, the partial
results are preserved instead of silently discarded.

Deferred descriptions
----------------------
LinkedIn search results never carry a full job description inline — jobspy
fetches it with a SEPARATE per-row GET only when `linkedin_fetch_description`
is True, which used to run at scrape time for every result (~9,000+ GETs/run,
~0.6s each, dwarfing the actual search traffic). Descriptions are now always
deferred: search calls come back title/company/url-only (same shape Workday
already returns), those flow through Stage 1's title-only gate in main.py,
and `fetch_descriptions()` below fills in descriptions only for the survivors
that actually reach Stage 2 — same pattern as sources/workday.py's
fetch_descriptions(), same shared rate limit as the search calls.
"""
from __future__ import annotations

import asyncio
import datetime as dt_mod
import logging
import math
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable

from config import HOURS_OLD, RESULTS_PER_SEARCH
from models.job import RawJob
from sources.base import SourceAdapter, SourceResult
from sources.rate_limiter import TokenBucket

logger = logging.getLogger(__name__)


# Per-site concurrency caps. LinkedIn is the only site that meaningfully
# rate-limits a single residential IP — keep it serial. Indeed and Google
# happily handle parallel requests.
_SITE_CONCURRENCY = {
    "linkedin": 1,
    "indeed": 6,
    "google": 3,
}

# Single shared rate gate for ALL LinkedIn traffic — both search calls
# (_scrape_one) and per-job description fetches (fetch_descriptions) draw
# from the same bucket, so total request volume to linkedin.com stays under
# one ceiling regardless of which phase is issuing them. 45/min matches the
# sustained rate the pipeline already ran at for hours without being blocked;
# a real token bucket lets requests through as soon as a token is available
# instead of a flat random.uniform(8, 16) sleep before every call.
_linkedin_bucket = TokenBucket(rate_per_min=45)

# jobspy's LinkedIn scraper sleeps `random.uniform(delay, delay + band_delay)`
# between its OWN internal pages within a single scrape_jobs() call (class
# attributes, default 3s/4s). Our bucket above already governs true
# call-level pacing, so this only needs to be polite enough to avoid tripping
# LinkedIn's own guest rate limiting, not act as the primary throttle.
# Guarded with hasattr so a future jobspy release that renames/removes these
# degrades to a log line, not a crash. Pin python-jobspy==1.1.82 in
# requirements.txt so this override target doesn't silently drift.
try:
    from jobspy.linkedin import LinkedIn as _JobspyLinkedIn
    if hasattr(_JobspyLinkedIn, "delay"):
        _JobspyLinkedIn.delay = 1
    if hasattr(_JobspyLinkedIn, "band_delay"):
        _JobspyLinkedIn.band_delay = 1
except Exception:
    logger.debug("Could not override jobspy LinkedIn pacing; using library defaults", exc_info=True)

# Extracts the numeric LinkedIn job id from a stored job_url of the form
# https://www.linkedin.com/jobs/view/{job_id}
_LINKEDIN_JOB_ID_RE = re.compile(r"/jobs/view/(\d+)")

# Pool of common desktop browser User-Agents. We rotate per scrape_jobs
# call so traffic from one IP looks like a household with multiple devices
# rather than a single bot.
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0",
]


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
        self._discovery_lock = threading.Lock()
        self._jobs_buffer: list[RawJob] = []
        self._buffer_lock = threading.Lock()
        self._errors_buffer: list[str] = []

    @property
    def discovered_workday_companies(self) -> list[dict]:
        with self._discovery_lock:
            return list(self._discovered.values())

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        """Scrape each site in its own pool, all running in parallel.

        Per-site pools mean LinkedIn's slow rate-limited path no longer
        starves Indeed/Google's fast paths. The accumulator buffer means
        results survive cancellation.
        """
        # Reset buffers for this run.
        with self._buffer_lock:
            self._jobs_buffer = []
            self._errors_buffer = []

        loop = asyncio.get_event_loop()
        site_tasks = [
            self._scrape_site(loop, site, titles, locations)
            for site in self.sites
        ]
        try:
            await asyncio.gather(*site_tasks, return_exceptions=True)
        except asyncio.CancelledError:
            logger.warning("LinkedIn/Indeed: scrape cancelled — returning partial buffer")
            raise
        finally:
            with self._buffer_lock:
                jobs = list(self._jobs_buffer)
                errors = list(self._errors_buffer)

        logger.info(f"LinkedIn/Indeed: scraped {len(jobs)} jobs across {len(self.sites)} sites")
        return SourceResult(jobs=jobs, errors=errors)

    async def _scrape_site(
        self, loop: asyncio.AbstractEventLoop, site: str, titles: list[str], locations: list[str]
    ) -> None:
        """Run all (title, location) queries for ONE site in its own bounded pool."""
        max_workers = _SITE_CONCURRENCY.get(site, 4)
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"jobspy-{site}") as pool:
            tasks = [
                loop.run_in_executor(pool, self._scrape_one, site, title, location)
                for title in titles
                for location in locations
            ]
            # Fire-and-forget completion — each future appends to the shared
            # buffer on its own. We just await all of them so this site
            # finishes before the parent scrape() returns.
            await asyncio.gather(*tasks, return_exceptions=True)

    def _scrape_one(self, site: str, title: str, location: str) -> None:
        from jobspy import scrape_jobs

        # Throttle LinkedIn between calls via the shared token bucket (single
        # worker means this naturally serializes LinkedIn's own traffic;
        # fetch_descriptions() draws from the same bucket for the deferred
        # per-job description fetches).
        if site == "linkedin":
            _linkedin_bucket.acquire()

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
                # Always deferred now — see module docstring "Deferred
                # descriptions". fetch_descriptions() fills these in later,
                # only for jobs that survive Stage 1's title-only gate.
                linkedin_fetch_description=False,
                user_agent=random.choice(_USER_AGENTS),
            )
        except Exception as e:
            msg = f"{site} scrape failed for '{title}' in '{location}': {e}"
            logger.warning(msg)
            with self._buffer_lock:
                self._errors_buffer.append(msg)
            return

        these_jobs: list[RawJob] = []
        for _, row in df.iterrows():
            raw_title = _safe_str(row.get("title"))
            raw_company = _safe_str(row.get("company"))
            # Passively discover Workday tenants from direct application URLs.
            # In practice job_url_direct is only ever populated when jobspy
            # fetches full descriptions, which no longer happens here — this
            # is now a no-op at scrape time and kept only for the (harmless)
            # case a future jobspy version starts returning it earlier.
            # The real discovery path is now in fetch_descriptions() below.
            direct_url = _safe_str(row.get("job_url_direct"))
            if direct_url and "myworkdayjobs.com" in direct_url and raw_company:
                from sources.workday_discovery import extract_workday_tenant
                discovery = extract_workday_tenant(direct_url, raw_company)
                if discovery:
                    with self._discovery_lock:
                        self._discovered.setdefault(discovery["tenant"], discovery)
            if not raw_title or not raw_company:
                continue

            these_jobs.append(
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

        if these_jobs:
            with self._buffer_lock:
                self._jobs_buffer.extend(these_jobs)

    async def fetch_descriptions(
        self,
        jobs: list[RawJob],
        concurrency: int = 4,
        on_progress: Callable[[int], None] | None = None,
    ) -> int:
        """Fetch full descriptions for LinkedIn jobs that survived Stage 1's
        title-only gate — mirrors sources/workday.py's fetch_descriptions().

        Uses jobspy's own LinkedIn._get_job_details(), the exact method it
        calls internally for `linkedin_fetch_description=True`, so markdown
        formatting stays identical to what the old inline-fetch path
        produced. Gated through the same shared token bucket as search calls
        so total LinkedIn request volume stays under one ceiling. This is
        also where Workday-tenant discovery now happens for LinkedIn rows
        (job_url_direct is only ever populated by this same detail fetch).
        """
        targets = [
            j for j in jobs
            if j.source == "linkedin" and not (j.description and j.description.strip())
        ]
        if not targets:
            return 0

        from jobspy.linkedin import LinkedIn
        from jobspy.model import DescriptionFormat, ScraperInput, Site

        scraper = LinkedIn()
        # _get_job_details() reads scraper_input.description_format — set it
        # to match jobspy's own default (markdown) so output stays consistent
        # with what the old inline-fetch path produced.
        scraper.scraper_input = ScraperInput(
            site_type=[Site.LINKEDIN], search_term="",
            description_format=DescriptionFormat.MARKDOWN,
        )

        loop = asyncio.get_event_loop()
        sem = asyncio.Semaphore(concurrency)

        async def _one(job: RawJob) -> bool:
            m = _LINKEDIN_JOB_ID_RE.search(job.url or "")
            if not m:
                if on_progress:
                    on_progress(1)
                return False
            job_id = m.group(1)
            async with sem:
                _linkedin_bucket.acquire()  # blocking call, but sem already
                # bounds how many threads can be waiting on it concurrently
                try:
                    details = await loop.run_in_executor(
                        None, scraper._get_job_details, job_id
                    )
                except Exception as e:
                    logger.debug(f"LinkedIn detail fetch failed for {job.url}: {e}")
                    if on_progress:
                        on_progress(1)
                    return False
            description = details.get("description") if details else None
            direct_url = details.get("job_url_direct") if details else None
            if direct_url and "myworkdayjobs.com" in direct_url:
                from sources.workday_discovery import extract_workday_tenant
                discovery = extract_workday_tenant(direct_url, job.company)
                if discovery:
                    with self._discovery_lock:
                        self._discovered.setdefault(discovery["tenant"], discovery)
            if on_progress:
                on_progress(1)
            if not description:
                return False
            job.description = description
            return True

        results = await asyncio.gather(*[_one(j) for j in targets])
        n_filled = sum(1 for r in results if r)
        logger.info(
            f"LinkedIn description fetch: {n_filled}/{len(targets)} filled "
            f"(concurrency={concurrency})"
        )
        return n_filled
