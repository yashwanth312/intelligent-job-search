"""Workday job board adapter — searches TARGET_TITLES per company via the public API."""
from __future__ import annotations

import asyncio
import logging

import aiohttp

from models.job import RawJob
from sources._dates import parse_iso
from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
}
_REQUEST_DELAY = 1.5   # seconds between title searches within one tenant
_MAX_RETRIES = 3
_PAGE_SIZE = 20


class WorkdayAdapter(SourceAdapter):
    name = "workday"

    def __init__(self, companies: list[dict]) -> None:
        """companies: list of {tenant, wd_server, site, name}"""
        self.companies = companies

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        all_jobs: list[RawJob] = []
        all_errors: list[str] = []

        async with aiohttp.ClientSession(headers=_HEADERS) as session:
            results = await asyncio.gather(
                *[self._scrape_company(session, company, titles)
                  for company in self.companies],
                return_exceptions=True,
            )

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                msg = f"Workday {self.companies[i]['name']}: {result}"
                logger.error(msg)
                all_errors.append(msg)
            else:
                jobs, errors = result
                all_jobs.extend(jobs)
                all_errors.extend(errors)

        logger.info(
            f"Workday: {len(all_jobs)} jobs from {len(self.companies)} companies"
        )
        return SourceResult(jobs=all_jobs, errors=all_errors)

    async def _scrape_company(
        self,
        session: aiohttp.ClientSession,
        company: dict,
        titles: list[str],
    ) -> tuple[list[RawJob], list[str]]:
        tenant = company["tenant"]
        wd_server = company["wd_server"]
        site = company["site"]
        name = company["name"]
        api_url = (
            f"https://{tenant}.{wd_server}.myworkdayjobs.com"
            f"/wday/cxs/{tenant}/{site}/jobs"
        )
        job_url_base = (
            f"https://{tenant}.{wd_server}.myworkdayjobs.com/en-US/{site}"
        )

        jobs: list[RawJob] = []
        errors: list[str] = []

        for i, title in enumerate(titles):
            if i > 0:
                await asyncio.sleep(_REQUEST_DELAY)

            postings, err = await self._search(session, api_url, title, name)
            if err:
                errors.append(err)
                continue

            for posting in postings:
                external_path = posting.get("externalPath", "")
                jobs.append(RawJob(
                    title=posting.get("title", ""),
                    company=name,
                    location=posting.get("locationsText", ""),
                    description=None,
                    url=f"{job_url_base}/{external_path}",
                    source=f"workday-{tenant}",
                    posted_at=parse_iso(posting.get("postedOn")),
                ))

        return jobs, errors

    async def _search(
        self,
        session: aiohttp.ClientSession,
        api_url: str,
        title: str,
        company_name: str,
    ) -> tuple[list[dict], str | None]:
        """Paginate through all results for one (company, title) pair."""
        all_postings: list[dict] = []
        offset = 0

        while True:
            body = {
                "searchText": title,
                "limit": _PAGE_SIZE,
                "offset": offset,
                "appliedFacets": {},
            }
            data, err = await self._post_with_retry(
                session, api_url, body, company_name, title
            )
            if err:
                return all_postings, err

            postings = data.get("jobPostings", [])
            all_postings.extend(postings)
            total = data.get("total", 0)
            offset += _PAGE_SIZE
            if offset >= total or not postings:
                break

        return all_postings, None

    async def _post_with_retry(
        self,
        session: aiohttp.ClientSession,
        url: str,
        body: dict,
        company_name: str,
        title: str,
    ) -> tuple[dict, str | None]:
        for attempt in range(_MAX_RETRIES):
            try:
                async with session.post(
                    url, json=body, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json(content_type=None), None
                    if resp.status == 429:
                        wait = 30 * (2 ** attempt)
                        logger.warning(
                            f"Workday {company_name}: 429 rate limit, "
                            f"waiting {wait}s (attempt {attempt + 1}/{_MAX_RETRIES})"
                        )
                        await asyncio.sleep(wait)
                        continue
                    logger.warning(
                        f"Workday {company_name} '{title}': HTTP {resp.status}"
                    )
                    return {}, None
            except Exception as e:
                logger.warning(
                    f"Workday {company_name} '{title}': request error: {e}"
                )
                return {}, f"{company_name} '{title}': {e}"

        return {}, (
            f"Workday {company_name} '{title}': "
            f"max retries exceeded after repeated 429s"
        )
