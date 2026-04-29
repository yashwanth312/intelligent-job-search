"""RemoteOK public JSON API adapter."""
from __future__ import annotations

import logging

import aiohttp

from models.job import RawJob
from sources._dates import parse_epoch, parse_iso
from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)

REMOTEOK_API = "https://remoteok.com/api"


class RemoteOKAdapter(SourceAdapter):
    name = "remoteok"

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        jobs: list[RawJob] = []
        errors: list[str] = []

        try:
            async with aiohttp.ClientSession() as session:
                jobs = await self._fetch_jobs(session)
        except Exception as e:
            msg = f"RemoteOK: {e}"
            logger.warning(msg)
            errors.append(msg)

        logger.info(f"RemoteOK: fetched {len(jobs)} jobs")
        return SourceResult(jobs=jobs, errors=errors)

    async def _fetch_jobs(self, session: aiohttp.ClientSession) -> list[RawJob]:
        headers = {"User-Agent": "IntelligentJobSearch/1.0"}
        async with session.get(REMOTEOK_API, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                logger.warning(f"RemoteOK: HTTP {resp.status}")
                return []
            data = await resp.json(content_type=None)

        jobs: list[RawJob] = []
        for item in data:
            # Skip metadata items (first item and items without 'position')
            if "position" not in item:
                continue

            salary_min = item.get("salary_min")
            salary_max = item.get("salary_max")
            posted_at = (
                parse_epoch(item.get("epoch"))
                or parse_iso(item.get("date"))
            )

            jobs.append(
                RawJob(
                    title=item.get("position", ""),
                    company=item.get("company", ""),
                    location=item.get("location", "Remote"),
                    description=item.get("description", ""),
                    salary_min=int(salary_min) if salary_min else None,
                    salary_max=int(salary_max) if salary_max else None,
                    url=item.get("url", ""),
                    source="remoteok",
                    posted_at=posted_at,
                )
            )

        return jobs
