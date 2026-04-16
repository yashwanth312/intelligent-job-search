"""Wellfound (AngelList) web scraper — stub implementation."""
from __future__ import annotations

import logging

from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)


class WellfoundAdapter(SourceAdapter):
    name = "wellfound"

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        logger.info("Wellfound adapter: stub — not yet implemented")
        return SourceResult(jobs=[], errors=[])
