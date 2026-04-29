"""H1B sponsor check via h1bdata.info — Phase 7 of the pipeline."""
from __future__ import annotations

import asyncio
import re
import urllib.parse
from datetime import datetime, timezone

import aiohttp

from db.database import Database
from models.job import RawJob

_LEGAL_SUFFIXES_RE = re.compile(
    r"\b(inc|llc|corp|ltd|l\.?p|plc|incorporated|limited|corporation)\b\.?",
    re.IGNORECASE,
)

_CURATED_PREFIXES = ("greenhouse-", "lever-", "ashby-")


class H1BChecker:
    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _normalize(company: str) -> str:
        """Return a canonical cache key for a company name."""
        name = _LEGAL_SUFFIXES_RE.sub("", company)
        name = re.sub(r"[^a-z0-9\s]", "", name.lower())
        return re.sub(r"\s+", " ", name).strip()

    @staticmethod
    def _has_results(html: str) -> bool:
        """Return True if the h1bdata.info HTML table contains at least one data row."""
        if "no data available in table" in html.lower():
            return False
        return bool(re.search(r"<tbody[^>]*>\s*<tr", html, re.IGNORECASE))

    async def _scrape_year(
        self, session: aiohttp.ClientSession, company_key: str, year: int
    ) -> bool:
        url = (
            "https://h1bdata.info/index.php"
            f"?em={urllib.parse.quote_plus(company_key)}&job=&city=&year={year}"
        )
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            html = await resp.text(errors="replace")
        return self._has_results(html)

    async def _check_company(
        self,
        sem: asyncio.Semaphore,
        session: aiohttp.ClientSession,
        company_key: str,
        company_raw: str,
    ) -> bool | None:
        """Return True/False from h1bdata.info, or None on any error."""
        async with sem:
            try:
                year = datetime.now(timezone.utc).year
                results = await asyncio.gather(
                    self._scrape_year(session, company_key, year),
                    self._scrape_year(session, company_key, year - 1),
                    return_exceptions=True,
                )
                if any(r is True for r in results):
                    return True
                if any(isinstance(r, BaseException) for r in results):
                    return None  # at least one request errored — don't penalise
                return False
            except Exception:
                return None

    async def check_batch(self, jobs: list[RawJob]) -> None:
        """Mutate h1b_sponsor_verified on open-source jobs in-place.

        Curated sources (greenhouse-*, lever-*, ashby-*) are left as None.
        Open-source jobs get True/False from cache or h1bdata.info scrape.
        Error results (None) are not cached and leave the field as None.
        """
        open_jobs = [j for j in jobs if not j.source.startswith(_CURATED_PREFIXES)]
        if not open_jobs:
            return

        # Group by normalized company key; keep one raw name per key
        by_key: dict[str, list[RawJob]] = {}
        raw_name: dict[str, str] = {}
        for job in open_jobs:
            key = self._normalize(job.company)
            if not key:
                continue
            by_key.setdefault(key, []).append(job)
            raw_name.setdefault(key, job.company)

        # Serve cache hits; collect misses
        verified: dict[str, bool | None] = {}
        misses: list[str] = []
        for key in by_key:
            hit = self._db.get_h1b_cache(key)
            if hit is not None:
                verified[key] = hit
            else:
                misses.append(key)

        # Scrape cache misses concurrently
        if misses:
            sem = asyncio.Semaphore(3)
            async with aiohttp.ClientSession(
                headers={"User-Agent": "Mozilla/5.0"},
            ) as session:
                results = await asyncio.gather(
                    *[
                        self._check_company(sem, session, key, raw_name[key])
                        for key in misses
                    ]
                )
            for key, result in zip(misses, results):
                verified[key] = result
                if result is not None:  # only cache definitive True/False
                    self._db.set_h1b_cache(key, raw_name[key], result)

        # Mutate jobs in-place
        for key, job_list in by_key.items():
            v = verified.get(key)
            for job in job_list:
                job.h1b_sponsor_verified = v


# Sources where "no H-1B history" reliably means "won't sponsor".
# These skew toward established companies; if they have zero LCA
# filings on record, dropping them is safe. New sources default to
# KEEP — explicitly add to this set/prefix when triaged.
_DROPPABLE_SOURCES = frozenset({"linkedin", "indeed", "google"})

# Per-tenant adapters emit `source=f"{adapter}-{tenant}"`. Workday
# tenants (e.g. "workday-broadcom") are big-company by construction.
_DROPPABLE_PREFIXES = ("workday-",)


def is_droppable_source(source: str) -> bool:
    """Return True if a source belongs to the big-company drop bucket.

    Sources outside this set are either user-curated (greenhouse/lever/ashby
    prefixes) or startup-heavy (hackernews, remoteok), where a missing
    h1bdata.info record is uninformative.
    """
    if source in _DROPPABLE_SOURCES:
        return True
    return source.startswith(_DROPPABLE_PREFIXES)


def partition_drops(jobs: list[RawJob]) -> tuple[list[RawJob], list[RawJob]]:
    """Split a list of H1B-checked jobs into (kept, dropped).

    A job is dropped iff its source is in the drop bucket AND its
    h1b_sponsor_verified is False (definitively no LCA filings).
    All other combinations — verified=True, verified=None, or any
    keep-bucket source — pass through unchanged.

    Pre-condition: callers should run H1BChecker.check_batch first so
    h1b_sponsor_verified is populated where applicable.
    """
    kept: list[RawJob] = []
    dropped: list[RawJob] = []
    for job in jobs:
        if job.h1b_sponsor_verified is False and is_droppable_source(job.source):
            dropped.append(job)
        else:
            kept.append(job)
    return kept, dropped
