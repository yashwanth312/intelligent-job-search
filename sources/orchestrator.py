"""Scraper orchestrator — runs all source adapters in parallel, deduplicates results."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from models.job import RawJob
from sources.base import SourceAdapter, SourceResult

# Callback signature: (adapter_name, job_count, error_message_or_None)
SourceDoneCallback = Callable[[str, int, "str | None"], None]

logger = logging.getLogger(__name__)

# Sources whose adapters already filter by age at scrape time (e.g. JobSpy
# passes hours_old to LinkedIn/Indeed/Google). For jobs from these sources
# with no parsed posted_at, we trust the source and keep them.
_PREFILTERED_SOURCES = {"linkedin", "indeed", "google"}


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

        # Deduplicate by fingerprint
        seen: set[str] = set(known_fingerprints or set())
        unique_jobs: list[RawJob] = []
        dupes = 0
        for job in all_jobs:
            if job.fingerprint not in seen:
                seen.add(job.fingerprint)
                unique_jobs.append(job)
            else:
                dupes += 1

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
