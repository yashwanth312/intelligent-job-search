"""Scraper orchestrator — runs all source adapters in parallel, deduplicates results."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from config import HOURS_OLD as _DEFAULT_HOURS_OLD
from models.job import RawJob
from sources.base import SourceAdapter, SourceResult

# Callback signature: (adapter_name, job_count, error_message_or_None)
SourceDoneCallback = Callable[[str, int, "str | None"], None]

logger = logging.getLogger(__name__)

# Sources whose adapters already filter by age at scrape time (e.g. JobSpy
# passes hours_old to LinkedIn/Indeed/Google). For jobs from these sources
# with no parsed posted_at, we trust the source and keep them.
_PREFILTERED_SOURCES = {"linkedin", "indeed", "google"}


def _is_fresh(job: RawJob, cutoff: datetime) -> bool:
    """Same freshness rule as filter_fresh_jobs, for one job at a time."""
    if job.posted_at is not None:
        return job.posted_at >= cutoff
    return job.source in _PREFILTERED_SOURCES


def prefer_fresher(a: RawJob, b: RawJob, hours_old: int) -> RawJob:
    """Given two RawJobs that collide on fingerprint, return the one that
    should survive dedup — preferring whichever one `filter_fresh_jobs` would
    call fresh over one it would call stale, then whichever has the more
    recent `posted_at` (unknown-but-trusted counts as "now").

    Fixes a real bug: dedup used to run before the freshness filter and kept
    whichever duplicate was encountered first (adapter order), so a 40-day-old
    Greenhouse listing could win the fingerprint slot and then die as stale in
    the freshness phase — taking a fresh LinkedIn repost of the same job down
    with it, since only one survives dedup.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    a_fresh, b_fresh = _is_fresh(a, cutoff), _is_fresh(b, cutoff)
    if a_fresh != b_fresh:
        return a if a_fresh else b
    # Both fresh or both stale — prefer the more recently posted; treat a
    # missing posted_at as "now" only when it's the trusted/fresh case above
    # already agreed, otherwise fall back to whichever has a real date.
    if a.posted_at is not None and b.posted_at is not None:
        return a if a.posted_at >= b.posted_at else b
    if a.posted_at is not None:
        return a
    if b.posted_at is not None:
        return b
    return a  # both unknown — arbitrary, stable choice


def filter_fresh_jobs(
    jobs: list[RawJob], hours_old: int
) -> tuple[list[RawJob], list[RawJob]]:
    """Split jobs into (fresh, stale) by posted_at and source trust policy.

    A job is fresh if:
      - posted_at is set and within `hours_old` of now (UTC), OR
      - posted_at is None AND source is in _PREFILTERED_SOURCES.

    Jobs from unprefiltered sources with no posted_at are treated as stale
    (we can't prove they're new, so we drop them).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    fresh: list[RawJob] = []
    stale: list[RawJob] = []
    for job in jobs:
        if job.posted_at is not None:
            if job.posted_at >= cutoff:
                fresh.append(job)
            else:
                stale.append(job)
        else:
            if job.source in _PREFILTERED_SOURCES:
                fresh.append(job)
            else:
                stale.append(job)
    return fresh, stale


class ScraperOrchestrator:
    def __init__(self, adapters: list[SourceAdapter]):
        self.adapters = adapters

    async def scrape_all(
        self, titles: list[str], locations: list[str],
        known_fingerprints: set[str] | None = None,
        on_source_done: SourceDoneCallback | None = None,
        hours_old: int | None = None,
    ) -> SourceResult:
        all_jobs: list[RawJob] = []
        all_errors: list[str] = []

        # Run all adapters in parallel
        tasks = [
            self._safe_scrape(adapter, titles, locations, on_source_done)
            for adapter in self.adapters
        ]
        results = await asyncio.gather(*tasks)

        for result in results:
            all_jobs.extend(result.jobs)
            all_errors.extend(result.errors)

        # Deduplicate by fingerprint. Jobs already known from a prior run are
        # dropped unconditionally. Jobs that collide WITHIN this run's batch
        # (e.g. the same posting from Greenhouse and a LinkedIn repost) are
        # resolved by freshness via prefer_fresher, not by which adapter
        # happens to run first — see prefer_fresher's docstring for the bug
        # this fixes.
        effective_hours_old = hours_old if hours_old is not None else _DEFAULT_HOURS_OLD
        known = known_fingerprints or set()
        best: dict[str, RawJob] = {}
        dupes = 0
        for job in all_jobs:
            fp = job.fingerprint
            if fp in known:
                dupes += 1
                continue
            existing = best.get(fp)
            if existing is None:
                best[fp] = job
            else:
                dupes += 1
                best[fp] = prefer_fresher(job, existing, effective_hours_old)

        unique_jobs = list(best.values())

        logger.info(
            f"Orchestrator: {len(all_jobs)} total, {dupes} duplicates removed, "
            f"{len(unique_jobs)} unique jobs"
        )

        return SourceResult(jobs=unique_jobs, errors=all_errors)

    async def _safe_scrape(
        self,
        adapter: SourceAdapter,
        titles: list[str],
        locations: list[str],
        on_source_done: SourceDoneCallback | None,
    ) -> SourceResult:
        try:
            result = await adapter.scrape(titles, locations)
            if on_source_done:
                err = result.errors[0] if result.errors else None
                on_source_done(adapter.name, len(result.jobs), err)
            return result
        except Exception as e:
            msg = f"{adapter.name}: {e}"
            logger.error(msg)
            if on_source_done:
                on_source_done(adapter.name, 0, str(e))
            return SourceResult(jobs=[], errors=[msg])
