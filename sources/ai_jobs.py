"""AI Jobs web scraper — stub implementation."""
from __future__ import annotations

import logging

from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)


class AIJobsAdapter(SourceAdapter):
    name = "ai_jobs"

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        logger.info("AI Jobs adapter: stub — not yet implemented")
        return SourceResult(jobs=[], errors=[])
