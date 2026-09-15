"""Base interface for all source adapters."""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import aiohttp

from models.job import RawJob

logger = logging.getLogger(__name__)

# Boards are small, independent GETs against different hosts, so they fan out
# cleanly. Bounded so a few hundred boards don't open a few hundred sockets.
DEFAULT_BOARD_CONCURRENCY = 8


@dataclass
class SourceResult:
    jobs: list[RawJob] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class SourceAdapter(ABC):
    name: str = "base"

    @abstractmethod
    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        ...


async def scrape_boards(
    companies: list[dict],
    scrape_one: Callable[[aiohttp.ClientSession, dict], Awaitable[list[RawJob]]],
    label: str,
    concurrency: int = DEFAULT_BOARD_CONCURRENCY,
    headers: dict | None = None,
) -> SourceResult:
    """Fetch every company board concurrently, collecting jobs and per-board errors.

    Shared by the board-style ATS adapters (Greenhouse, Lever, Ashby), which all
    do the same thing: one independent request per company, filter titles
    client-side, move on.

    These adapters each looped their company list sequentially, awaiting one
    board before starting the next. That was invisible at ~100 boards and became
    the dominant cost once bulk discovery pushed the list into the hundreds —
    a board takes ~0.3s, so 1,000 of them serially is several minutes of the run
    spent waiting on a socket. One failing board never fails the batch.
    """
    jobs: list[RawJob] = []
    errors: list[str] = []
    sem = asyncio.Semaphore(concurrency)

    async def one(session: aiohttp.ClientSession, company: dict) -> None:
        async with sem:
            try:
                jobs.extend(await scrape_one(session, company))
            except Exception as e:
                msg = f"{label} {company.get('name', company.get('token', '?'))}: {e}"
                logger.warning(msg)
                errors.append(msg)

    async with aiohttp.ClientSession(headers=headers or {}) as session:
        await asyncio.gather(*[one(session, c) for c in companies])

    logger.info(
        f"{label}: scraped {len(jobs)} relevant jobs from {len(companies)} companies"
        + (f" ({len(errors)} board error(s))" if errors else "")
    )
    return SourceResult(jobs=jobs, errors=errors)
