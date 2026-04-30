"""Workday job board adapter — searches TARGET_TITLES per company via the public API."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Callable

import aiohttp
from bs4 import BeautifulSoup

from models.job import RawJob
from sources._dates import parse_iso
from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)

# Parses the public-facing job URL into the components needed to build the
# Workday detail API endpoint.
# Public form: https://{tenant}.{wd_server}.myworkdayjobs.com[/{locale}]/{site}/{external_path}
_DETAIL_URL_RE = re.compile(
    r"^https?://([^.]+)\.(wd\d+)\.myworkdayjobs\.com"
    r"(?:/(?i:[a-z]{2}-[a-z]{2}))?/([^/]+)/(.+)$"
)

# Minimum extracted text length to consider a Workday description usable.
_MIN_DESC_LENGTH = 50

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
        # locations unused: Workday searches are title-scoped; location filtering
        # applied post-scrape by Stage 1 and Stage 2 screening.
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
            if err == "__422__":
                logger.warning(
                    f"Workday {name}: board returned 422 (requires auth or config wrong) "
                    "— skipping all remaining titles for this company"
                )
                errors.append(f"{name}: HTTP 422 — board not publicly accessible")
                break
            if err:
                errors.append(err)
                continue

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
                    if resp.status == 422:
                        # Board requires authentication or tenant/site config is wrong.
                        # Return a sentinel so _scrape_company can bail out of all
                        # remaining titles rather than logging 30+ identical warnings.
                        return {}, "__422__"
                    logger.warning(
                        f"Workday {company_name} '{title}': HTTP {resp.status}"
                    )
                    return {}, None
            except Exception as e:
                logger.warning(
                    f"Workday {company_name} '{title}': request error: {e}"
                )
                if attempt == _MAX_RETRIES - 1:
                    return {}, f"{company_name} '{title}': {e}"
                await asyncio.sleep(5 * (2 ** attempt))
                continue

        return {}, (
            f"Workday {company_name} '{title}': "
            f"max retries exceeded after repeated 429s"
        )


# ── Description backfill (post-Stage-1) ────────────────────────────────────
# Workday search endpoints don't return job descriptions. We fetch them on
# demand AFTER Stage 1's title-only filter trims the list, so volume is
# small (~50–200 fetches/run) and we only pay the cost on jobs whose title
# already cleared screening. Survivors then get a full Stage 1 pass + Stage 2.

def _build_detail_url(public_url: str) -> str | None:
    """Convert a public Workday job URL to its JSON detail API endpoint.

    Returns None if the URL doesn't match the expected pattern.
    """
    m = _DETAIL_URL_RE.match(public_url)
    if not m:
        return None
    tenant, wd_server, site, external_path = m.groups()
    # external_path already contains "job/..." — don't re-prefix.
    return (
        f"https://{tenant}.{wd_server}.myworkdayjobs.com"
        f"/wday/cxs/{tenant}/{site}/{external_path}"
    )


def _extract_description(detail_payload: dict) -> str | None:
    """Pull jobDescription HTML out of a Workday detail-API response and
    return the stripped plain text, or None if too short / missing.
    """
    posting_info = (detail_payload or {}).get("jobPostingInfo") or {}
    desc_html = posting_info.get("jobDescription") or ""
    if not desc_html:
        return None
    text = BeautifulSoup(desc_html, "html.parser").get_text(
        separator="\n", strip=True
    )
    if len(text) < _MIN_DESC_LENGTH:
        return None
    return text


async def _fetch_one_description(
    sem: asyncio.Semaphore,
    session: aiohttp.ClientSession,
    job: RawJob,
    timeout: float,
) -> bool:
    api_url = _build_detail_url(job.url)
    if not api_url:
        return False
    async with sem:
        try:
            async with session.get(
                api_url, timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json(content_type=None)
        except Exception as e:
            logger.debug(
                f"Workday detail fetch failed for {job.company} — {job.title}: {e}"
            )
            return False
    text = _extract_description(data)
    if not text:
        return False
    job.description = text
    return True


async def fetch_descriptions(
    jobs: list[RawJob],
    concurrency: int = 8,
    timeout: float = 15.0,
    on_progress: Callable[[int], None] | None = None,
) -> int:
    """Fetch jobDescription text for Workday jobs missing descriptions.

    Operates only on jobs whose source starts with 'workday-' AND whose
    description is currently None/empty. Mutates each job's description
    field in place. Returns the count of jobs successfully filled.
    """
    targets = [
        j for j in jobs
        if j.source.startswith("workday-")
        and not (j.description and j.description.strip())
    ]
    if not targets:
        return 0

    sem = asyncio.Semaphore(concurrency)

    async def _one(session: aiohttp.ClientSession, job: RawJob) -> bool:
        ok = await _fetch_one_description(sem, session, job, timeout)
        if on_progress:
            on_progress(1)
        return ok

    async with aiohttp.ClientSession(headers=_HEADERS) as session:
        results = await asyncio.gather(*[_one(session, j) for j in targets])

    n_filled = sum(1 for r in results if r)
    logger.info(
        f"Workday description fetch: {n_filled}/{len(targets)} filled "
        f"(concurrency={concurrency}, timeout={timeout}s)"
    )
    return n_filled
