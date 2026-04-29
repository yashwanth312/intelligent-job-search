# sources/backfill.py
"""Backfill missing job descriptions by fetching the job URL."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Callable

import aiohttp
from bs4 import BeautifulSoup

from models.job import RawJob

logger = logging.getLogger(__name__)

# Tags that add noise but are NOT script — keep script so JSON-LD can be read first
_STRIP_TAGS = ["style", "nav", "header", "footer", "noscript", "iframe"]

_MIN_DESC_LENGTH = 50
_MAX_DESC_LENGTH = 15000

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_CONCURRENT_FETCHES = 10

# LinkedIn-specific selectors for the "About the job" section
_LINKEDIN_SELECTORS = [
    ".description__text",
    ".show-more-less-html__markup",
    "[data-testid='job-details-about-the-job-container']",
]

# Generic job-description selectors used by common ATS platforms
_GENERIC_SELECTORS = [
    ".job-description",
    "#job-details",
    "article.job-description",
    "section.description",
    "[class*='jobDescription']",
    "[id*='jobDescription']",
]


@dataclass
class BackfillResult:
    filled: int
    failed: int
    skipped: int


def extract_description_from_html(html: str, url: str = "") -> str | None:
    """Extract the job description from an HTML page.

    Strategy (in order):
    1. JSON-LD structured data — server-rendered, used by Greenhouse/Lever/many ATS
    2. LinkedIn-specific CSS selectors — targets the "About the job" section exactly
    3. Generic job-description CSS selectors — common ATS patterns
    4. Full-page get_text() fallback — strips boilerplate tags, grabs remaining text
    """
    if not html or not html.strip():
        return None

    soup = BeautifulSoup(html, "html.parser")

    # 1. JSON-LD structured data (before stripping any script tags)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            desc = (data if isinstance(data, dict) else {}).get("description", "")
            if desc and len(desc) >= _MIN_DESC_LENGTH:
                # JSON-LD descriptions are often HTML — strip inner tags
                clean = BeautifulSoup(desc, "html.parser").get_text(separator="\n", strip=True)
                if len(clean) >= _MIN_DESC_LENGTH:
                    return clean[:_MAX_DESC_LENGTH]
        except Exception:
            pass

    # 2. LinkedIn-specific selectors
    if "linkedin.com" in url:
        for sel in _LINKEDIN_SELECTORS:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if len(text) >= _MIN_DESC_LENGTH:
                    return text[:_MAX_DESC_LENGTH]

    # 3. Generic selectors (ATS platforms)
    for sel in _GENERIC_SELECTORS:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) >= _MIN_DESC_LENGTH:
                return text[:_MAX_DESC_LENGTH]

    # 4. Full-page fallback — strip noise tags then get_text()
    for tag in soup(["script"] + _STRIP_TAGS):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    if not text or len(text) < _MIN_DESC_LENGTH:
        return None
    return text[:_MAX_DESC_LENGTH]


async def _fetch_one(
    session: aiohttp.ClientSession, url: str, timeout: float,
) -> str | None:
    """Fetch a single URL and extract description text."""
    try:
        async with session.get(
            url, headers=_HEADERS,
            timeout=aiohttp.ClientTimeout(total=timeout),
            allow_redirects=True,
        ) as resp:
            if resp.status == 999:
                logger.debug(f"Backfill: LinkedIn rate-limited (999) for {url}")
                return None
            if resp.status != 200:
                logger.debug(f"Backfill HTTP {resp.status} for {url}")
                return None
            html = await resp.text()
            return extract_description_from_html(html, url=url)
    except Exception as e:
        logger.debug(f"Backfill fetch error for {url}: {e}")
        return None


async def backfill_descriptions(
    jobs: list[RawJob],
    concurrency: int = _CONCURRENT_FETCHES,
    timeout: float = 15.0,
    on_progress: Callable[[int], None] | None = None,
) -> BackfillResult:
    """Fetch descriptions from URLs for jobs that are missing them.

    Fetches up to `concurrency` URLs in parallel (default 10).
    Mutates each job's `description` field in place when successful.
    If `on_progress` is provided, it's called with `1` after each job
    completes (success or failure) — for wiring a progress bar.
    """
    needs_backfill = [
        j for j in jobs
        if not (j.description and j.description.strip()) and j.url.strip()
    ]
    skipped = len(jobs) - len(needs_backfill)

    if not needs_backfill:
        logger.info("Backfill: no jobs need description fetching")
        return BackfillResult(filled=0, failed=0, skipped=skipped)

    logger.info(
        f"Backfill: fetching descriptions for {len(needs_backfill)} jobs "
        f"(concurrency={concurrency})"
    )

    sem = asyncio.Semaphore(concurrency)

    async def _fetch_job(session: aiohttp.ClientSession, job: RawJob) -> str:
        async with sem:
            text = await _fetch_one(session, job.url, timeout)
        if text:
            job.description = text
            logger.debug(f"Backfill OK: {job.company} — {job.title}")
            result = "filled"
        else:
            logger.debug(f"Backfill FAIL: {job.company} — {job.title}")
            result = "failed"
        if on_progress:
            on_progress(1)
        return result

    async with aiohttp.ClientSession() as session:
        outcomes = await asyncio.gather(
            *[_fetch_job(session, job) for job in needs_backfill]
        )

    filled = outcomes.count("filled")
    failed = outcomes.count("failed")
    logger.info(f"Backfill: {filled} filled, {failed} failed, {skipped} skipped (has desc or no url)")
    return BackfillResult(filled=filled, failed=failed, skipped=skipped)


async def fetch_description_from_url(url: str, timeout: float = 15.0) -> str | None:
    """One-shot fetch for a single URL. Used by generate_materials fallback."""
    async with aiohttp.ClientSession() as session:
        return await _fetch_one(session, url, timeout)
