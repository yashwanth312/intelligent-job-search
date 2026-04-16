"""HackerNews 'Who is Hiring' monthly thread adapter via Algolia API."""
from __future__ import annotations

import logging
import re
from datetime import datetime

import aiohttp

from models.job import RawJob
from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)

ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search"
ALGOLIA_ITEM = "https://hn.algolia.com/api/v1/items"


def parse_hn_comment(text: str, fallback_url: str) -> RawJob | None:
    """Parse a HN job comment in format: Company | Role | Location | ..."""
    if not text or "|" not in text:
        return None

    first_line = text.split("\n")[0].strip()
    parts = [p.strip() for p in first_line.split("|")]

    if len(parts) < 2:
        return None

    company = parts[0]
    title = parts[1]
    location = parts[2] if len(parts) > 2 else "Not specified"

    # Skip if company or title look like non-job content
    if len(company) > 100 or len(title) > 100:
        return None
    if not company or not title:
        return None

    # Extract URL from the comment body if present
    url_match = re.search(r'https?://\S+', text)
    url = url_match.group(0) if url_match else fallback_url

    # Full comment (after first line) is the description
    lines = text.split("\n")
    description = "\n".join(lines[1:]).strip() if len(lines) > 1 else None

    return RawJob(
        title=title,
        company=company,
        location=location,
        description=description,
        url=url,
        source="hackernews",
    )


class HackerNewsAdapter(SourceAdapter):
    name = "hackernews"

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        jobs: list[RawJob] = []
        errors: list[str] = []

        try:
            async with aiohttp.ClientSession() as session:
                thread_id = await self._find_latest_thread(session)
                if not thread_id:
                    return SourceResult(jobs=[], errors=["No 'Who is Hiring' thread found"])

                comments = await self._fetch_comments(session, thread_id)

                for comment in comments:
                    text = comment.get("text", "")
                    comment_id = comment.get("id", "")
                    fallback_url = f"https://news.ycombinator.com/item?id={comment_id}"

                    job = parse_hn_comment(text, fallback_url)
                    if job:
                        jobs.append(job)

        except Exception as e:
            msg = f"HackerNews: {e}"
            logger.warning(msg)
            errors.append(msg)

        logger.info(f"HackerNews: parsed {len(jobs)} jobs from Who's Hiring thread")
        return SourceResult(jobs=jobs, errors=errors)

    async def _find_latest_thread(self, session: aiohttp.ClientSession) -> int | None:
        params = {
            "query": '"Ask HN: Who is hiring?"',
            "tags": "story",
            "numericFilters": "created_at_i>0",
        }
        async with session.get(ALGOLIA_SEARCH, params=params) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()

        hits = data.get("hits", [])
        for hit in hits:
            title = hit.get("title", "")
            if "who is hiring" in title.lower() and "ask hn" in title.lower():
                return int(hit["objectID"])
        return None

    async def _fetch_comments(self, session: aiohttp.ClientSession, story_id: int) -> list[dict]:
        url = f"{ALGOLIA_ITEM}/{story_id}"
        async with session.get(url) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()

        return data.get("children", [])
