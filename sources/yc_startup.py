"""YC Startup (Y Combinator Work at a Startup) web scraper — stub implementation."""
from __future__ import annotations

import logging

from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)


class YCStartupAdapter(SourceAdapter):
    name = "yc_startup"

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        logger.info("YC Startup adapter: stub — not yet implemented")
        return SourceResult(jobs=[], errors=[])
