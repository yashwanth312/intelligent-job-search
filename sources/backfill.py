# sources/backfill.py
"""Backfill missing job descriptions by fetching the job URL."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import aiohttp
from bs4 import BeautifulSoup

from models.job import RawJob

logger = logging.getLogger(__name__)

# Tags that add noise, not job description content
_STRIP_TAGS = ["script", "style", "nav", "header", "footer", "noscript", "iframe"]

# Minimum extracted text length to consider it a real description
_MIN_DESC_LENGTH = 50

# Maximum description length to store
_MAX_DESC_LENGTH = 5000

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


@dataclass
class BackfillResult:
    filled: int
    failed: int
    skipped: int


def extract_description_from_html(html: str) -> str | None:
    """Extract meaningful text from an HTML page, stripping boilerplate."""
    if not html or not html.strip():
        return None

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(_STRIP_TAGS):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)

    if not text or len(text) < _MIN_DESC_LENGTH:
        return None

    return text[:_MAX_DESC_LENGTH]


async def _fetch_one(
    session: aiohttp.ClientSession, url: str, timeout: float,
) -> str | None:
    """Fetch a single URL and extract description text."""
    headers = {"User-Agent": _USER_AGENT}
    try:
        async with session.get(
            url, headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
            allow_redirects=True,
        ) as resp:
            if resp.status != 200:
                logger.debug(f"Backfill HTTP {resp.status} for {url}")
                return None
            html = await resp.text()
            return extract_description_from_html(html)
    except Exception as e:
        logger.debug(f"Backfill fetch error for {url}: {e}")
        return None


async def backfill_descriptions(
    jobs: list[RawJob],
    delay: float = 1.5,
    timeout: float = 15.0,
) -> BackfillResult:
    """Fetch descriptions from URLs for jobs that are missing them.

    Mutates each job's `description` field in place when successful.
    """
    needs_backfill = [
        j for j in jobs
        if not (j.description and j.description.strip()) and j.url.strip()
    ]
    skipped = len(jobs) - len(needs_backfill)
    filled = 0
    failed = 0

    if not needs_backfill:
        logger.info("Backfill: no jobs need description fetching")
        return BackfillResult(filled=0, failed=0, skipped=skipped)

    logger.info(f"Backfill: attempting to fetch descriptions for {len(needs_backfill)} jobs")

    async with aiohttp.ClientSession() as session:
        for job in needs_backfill:
            text = await _fetch_one(session, job.url, timeout)
            if text:
                job.description = text
                filled += 1
                logger.debug(f"Backfill OK: {job.company} — {job.title}")
            else:
                failed += 1
                logger.debug(f"Backfill FAIL: {job.company} — {job.title}")

            if delay > 0:
                await asyncio.sleep(delay)

    logger.info(f"Backfill: {filled} filled, {failed} failed, {skipped} skipped (has desc or no url)")
    return BackfillResult(filled=filled, failed=failed, skipped=skipped)


async def fetch_description_from_url(url: str, timeout: float = 15.0) -> str | None:
    """One-shot fetch for a single URL. Used by generate_materials fallback."""
    async with aiohttp.ClientSession() as session:
        return await _fetch_one(session, url, timeout)
