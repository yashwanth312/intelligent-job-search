"""Scraper orchestrator — runs all source adapters in parallel, deduplicates results."""
from __future__ import annotations

import asyncio
import logging

from models.job import RawJob
from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)


class ScraperOrchestrator:
    def __init__(self, adapters: list[SourceAdapter]):
        self.adapters = adapters

    async def scrape_all(
        self, titles: list[str], locations: list[str],
        known_fingerprints: set[str] | None = None,
    ) -> SourceResult:
        all_jobs: list[RawJob] = []
        all_errors: list[str] = []

        # Run all adapters in parallel
        tasks = [
            self._safe_scrape(adapter, titles, locations)
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
        self, adapter: SourceAdapter, titles: list[str], locations: list[str]
    ) -> SourceResult:
        try:
            return await adapter.scrape(titles, locations)
        except Exception as e:
            msg = f"{adapter.name}: {e}"
            logger.error(msg)
            return SourceResult(jobs=[], errors=[msg])
