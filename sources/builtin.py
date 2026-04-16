"""BuiltIn web scraper — stub implementation."""
from __future__ import annotations

import logging

from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)


class BuiltInAdapter(SourceAdapter):
    name = "builtin"

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        logger.info("BuiltIn adapter: stub — not yet implemented")
        return SourceResult(jobs=[], errors=[])
