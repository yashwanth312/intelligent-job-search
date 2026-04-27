# Workday Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a WorkdayAdapter that searches TARGET_TITLES across a seeded list of H-1B-sponsoring companies on Workday, plus passively discovers new Workday tenants from LinkedIn/Indeed results and appends them to `target_companies.yaml` automatically.

**Architecture:** `WorkdayAdapter` posts per-title searches to each company's Workday API in parallel across companies, sequential within a company (1.5s delay). `workday_discovery.py` parses `myworkdayjobs.com` URLs from LinkedIn/Indeed's `job_url_direct` column and persists new tenants to `target_companies.yaml` via `ruamel.yaml` (comment-preserving). All Workday jobs flow through the existing backfill → Stage 1 → Stage 2 pipeline unchanged.

**Tech Stack:** `aiohttp` (existing), `ruamel.yaml>=0.17` (add to requirements), `asyncio`, `re`, Python 3.12

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `requirements.txt` | Modify | Add `ruamel.yaml>=0.17` |
| `sources/workday_discovery.py` | Create | URL parser + yaml writer |
| `sources/workday.py` | Create | WorkdayAdapter — scrapes Workday API |
| `sources/linkedin_indeed.py` | Modify | Scan `job_url_direct` for Workday URLs |
| `scripts/verify_workday_tokens.py` | Create | Validate/discover Workday tenant configs |
| `target_companies.yaml` | Modify | Add verified `workday:` seed section |
| `main.py` | Modify | Wire adapter + discovery save after Phase 3 |
| `tests/test_workday_discovery.py` | Create | Tests for URL parsing and yaml writing |
| `tests/test_workday.py` | Create | Tests for WorkdayAdapter |

---

## Task 1: Add ruamel.yaml to requirements.txt

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Check current requirements.txt**

```bash
cat requirements.txt
```

- [ ] **Step 2: Add ruamel.yaml**

Open `requirements.txt` and add this line after the `pyyaml` entry (or at the end):
```
ruamel.yaml>=0.17
```

- [ ] **Step 3: Verify it installs cleanly**

```bash
pip install ruamel.yaml>=0.17
```
Expected: already satisfied (v0.17.21 is installed) or installs cleanly.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add ruamel.yaml to requirements for comment-preserving yaml writes"
```

---

## Task 2: workday_discovery.py — URL parser and yaml writer

**Files:**
- Create: `sources/workday_discovery.py`
- Create: `tests/test_workday_discovery.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_workday_discovery.py`:

```python
"""Tests for Workday tenant discovery and yaml persistence."""
from __future__ import annotations

import os
import tempfile

import pytest
import yaml

from sources.workday_discovery import extract_workday_tenant, save_new_companies


class TestExtractWorkdayTenant:
    def test_extract_standard_url(self):
        url = "https://microsoft.wd5.myworkdayjobs.com/External_Careers/job/Redmond/CE_JR1"
        result = extract_workday_tenant(url, "Microsoft")
        assert result == {
            "tenant": "microsoft",
            "wd_server": "wd5",
            "site": "External_Careers",
            "name": "Microsoft",
        }

    def test_extract_url_with_locale(self):
        url = "https://salesforce.wd12.myworkdayjobs.com/en-US/External_Career_Site/job/x"
        result = extract_workday_tenant(url, "Salesforce")
        assert result["tenant"] == "salesforce"
        assert result["wd_server"] == "wd12"
        assert result["site"] == "External_Career_Site"
        assert result["name"] == "Salesforce"

    def test_non_workday_url_returns_none(self):
        assert extract_workday_tenant("https://linkedin.com/jobs/view/123", "Co") is None

    def test_empty_string_returns_none(self):
        assert extract_workday_tenant("", "Co") is None

    def test_none_returns_none(self):
        assert extract_workday_tenant(None, "Co") is None

    def test_tenant_lowercased(self):
        url = "https://CrowdStrike.wd5.myworkdayjobs.com/CrowdStrikeCareers/job/x"
        result = extract_workday_tenant(url, "CrowdStrike")
        assert result["tenant"] == "crowdstrike"
        assert result["wd_server"] == "wd5"


class TestSaveNewCompanies:
    def _tmp_yaml(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        f.write(content)
        f.close()
        return f.name

    def test_adds_new_company_to_empty_workday_section(self):
        path = self._tmp_yaml("greenhouse:\n  - token: anthropic\n    name: Anthropic\n")
        try:
            added = save_new_companies(
                [{"tenant": "crowdstrike", "wd_server": "wd5",
                  "site": "CrowdStrikeCareers", "name": "CrowdStrike"}],
                yaml_path=path,
            )
            assert added == 1
            with open(path) as f:
                data = yaml.safe_load(f)
            assert len(data["workday"]) == 1
            assert data["workday"][0]["tenant"] == "crowdstrike"
        finally:
            os.unlink(path)

    def test_skips_existing_tenant(self):
        path = self._tmp_yaml(
            "workday:\n  - tenant: microsoft\n    wd_server: wd5\n"
            "    site: External_Careers\n    name: Microsoft\n"
        )
        try:
            added = save_new_companies(
                [{"tenant": "microsoft", "wd_server": "wd5",
                  "site": "External_Careers", "name": "Microsoft"}],
                yaml_path=path,
            )
            assert added == 0
        finally:
            os.unlink(path)

    def test_deduplicates_within_input_list(self):
        path = self._tmp_yaml("")
        try:
            added = save_new_companies(
                [
                    {"tenant": "okta", "wd_server": "wd5", "site": "okta", "name": "Okta"},
                    {"tenant": "okta", "wd_server": "wd5", "site": "okta", "name": "Okta"},
                ],
                yaml_path=path,
            )
            assert added == 1
        finally:
            os.unlink(path)

    def test_empty_discoveries_returns_zero(self):
        path = self._tmp_yaml("")
        try:
            assert save_new_companies([], yaml_path=path) == 0
        finally:
            os.unlink(path)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_workday_discovery.py -v
```
Expected: `ModuleNotFoundError: No module named 'sources.workday_discovery'`

- [ ] **Step 3: Create sources/workday_discovery.py**

```python
"""Passive Workday tenant discovery from LinkedIn/Indeed job_url_direct fields."""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Matches: https://{tenant}.{wd_server}.myworkdayjobs.com[/{locale}]/{site}/...
_WORKDAY_RE = re.compile(
    r"^https?://([^.]+)\.(wd\d+)\.myworkdayjobs\.com"
    r"(?:/[a-z]{2}-[A-Z]{2})?/([^/?#]+)",
    re.IGNORECASE,
)


def extract_workday_tenant(url: str | None, company_name: str) -> dict | None:
    """Parse a myworkdayjobs.com URL and return {tenant, wd_server, site, name}.

    Returns None if the URL is not a Workday URL or cannot be parsed.
    """
    if not url or "myworkdayjobs.com" not in url.lower():
        return None
    m = _WORKDAY_RE.match(url)
    if not m:
        return None
    return {
        "tenant": m.group(1).lower(),
        "wd_server": m.group(2).lower(),
        "site": m.group(3),
        "name": company_name,
    }


def save_new_companies(
    discoveries: list[dict],
    yaml_path: str = "target_companies.yaml",
) -> int:
    """Append entries not already present (by tenant) to the workday: section
    of target_companies.yaml. Returns the count of newly added companies.
    Uses ruamel.yaml to preserve existing comments and formatting.
    """
    if not discoveries:
        return 0
    try:
        from ruamel.yaml import YAML

        ryaml = YAML()
        ryaml.preserve_quotes = True

        with open(yaml_path) as f:
            data = ryaml.load(f) or {}

        if "workday" not in data:
            data["workday"] = []

        existing_tenants: set[str] = {c["tenant"] for c in data["workday"]}
        added = 0
        seen_in_batch: set[str] = set()
        for d in discoveries:
            tenant = d["tenant"]
            if tenant not in existing_tenants and tenant not in seen_in_batch:
                data["workday"].append(d)
                seen_in_batch.add(tenant)
                added += 1

        if added > 0:
            with open(yaml_path, "w") as f:
                ryaml.dump(data, f)

        return added
    except Exception as e:
        logger.error(f"Workday discovery: failed to update {yaml_path}: {e}")
        return 0
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_workday_discovery.py -v
```
Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add sources/workday_discovery.py tests/test_workday_discovery.py
git commit -m "feat: add workday_discovery module — URL parser and yaml writer"
```

---

## Task 3: WorkdayAdapter

**Files:**
- Create: `sources/workday.py`
- Create: `tests/test_workday.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_workday.py`:

```python
"""Tests for WorkdayAdapter."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sources.workday import WorkdayAdapter

COMPANY = {
    "tenant": "testco",
    "wd_server": "wd5",
    "site": "TestCo_Careers",
    "name": "TestCo",
}


class AsyncCM:
    """Minimal async context manager for mocking aiohttp responses."""
    def __init__(self, value):
        self._value = value
    async def __aenter__(self):
        return self._value
    async def __aexit__(self, *args):
        pass


def _mock_resp(status: int, payload: dict) -> AsyncMock:
    r = AsyncMock()
    r.status = status
    r.json = AsyncMock(return_value=payload)
    return r


class TestWorkdayAdapter:
    @pytest.mark.asyncio
    async def test_scrape_converts_response_to_raw_jobs(self):
        adapter = WorkdayAdapter(companies=[COMPANY])
        resp = _mock_resp(200, {
            "total": 1,
            "jobPostings": [{
                "title": "Cloud Engineer",
                "externalPath": "job/Austin-TX/Cloud-Engineer_JR001",
                "locationsText": "Austin, Texas",
                "postedOn": "2026-04-25",
            }],
        })
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncCM(resp))

        with patch("asyncio.sleep"):
            jobs, errors = await adapter._scrape_company(
                mock_session, COMPANY, ["Cloud Engineer"]
            )

        assert len(jobs) == 1
        assert jobs[0].title == "Cloud Engineer"
        assert jobs[0].company == "TestCo"
        assert jobs[0].location == "Austin, Texas"
        assert jobs[0].source == "workday-testco"
        assert jobs[0].description is None
        assert "testco.wd5.myworkdayjobs.com/en-US/TestCo_Careers" in jobs[0].url
        assert "job/Austin-TX/Cloud-Engineer_JR001" in jobs[0].url
        assert errors == []

    @pytest.mark.asyncio
    async def test_pagination_fetches_all_pages(self):
        adapter = WorkdayAdapter(companies=[COMPANY])
        page1 = _mock_resp(200, {
            "total": 25,
            "jobPostings": [
                {"title": "Cloud Engineer", "externalPath": f"job/x_JR{i:03d}",
                 "locationsText": "Remote", "postedOn": "2026-04-25"}
                for i in range(20)
            ],
        })
        page2 = _mock_resp(200, {
            "total": 25,
            "jobPostings": [
                {"title": "Cloud Engineer", "externalPath": f"job/x_JR{i:03d}",
                 "locationsText": "Remote", "postedOn": "2026-04-25"}
                for i in range(20, 25)
            ],
        })
        mock_session = MagicMock()
        mock_session.post = MagicMock(
            side_effect=[AsyncCM(page1), AsyncCM(page2)]
        )

        with patch("asyncio.sleep"):
            jobs, _ = await adapter._scrape_company(
                mock_session, COMPANY, ["Cloud Engineer"]
            )

        assert mock_session.post.call_count == 2
        assert len(jobs) == 25

    @pytest.mark.asyncio
    async def test_429_triggers_backoff_and_succeeds_on_retry(self):
        adapter = WorkdayAdapter(companies=[COMPANY])
        r429 = AsyncMock()
        r429.status = 429
        r200 = _mock_resp(200, {
            "total": 1,
            "jobPostings": [{
                "title": "Cloud Engineer", "externalPath": "job/x_JR1",
                "locationsText": "Remote", "postedOn": "2026-04-25",
            }],
        })
        mock_session = MagicMock()
        mock_session.post = MagicMock(
            side_effect=[AsyncCM(r429), AsyncCM(r200)]
        )

        sleep_durations: list[float] = []
        with patch("asyncio.sleep", side_effect=lambda s: sleep_durations.append(s)):
            data, err = await adapter._post_with_retry(
                mock_session,
                "https://testco.wd5.myworkdayjobs.com/wday/cxs/testco/TestCo_Careers/jobs",
                {},
                "TestCo",
                "Cloud Engineer",
            )

        assert err is None
        assert data["total"] == 1
        assert any(s >= 30 for s in sleep_durations)  # backoff sleep occurred

    @pytest.mark.asyncio
    async def test_non_200_non_429_returns_empty_no_error(self):
        adapter = WorkdayAdapter(companies=[COMPANY])
        r404 = AsyncMock()
        r404.status = 404
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncCM(r404))

        data, err = await adapter._post_with_retry(
            mock_session,
            "https://testco.wd5.myworkdayjobs.com/wday/cxs/testco/TestCo_Careers/jobs",
            {},
            "TestCo",
            "Cloud Engineer",
        )

        assert data == {}
        assert err is None

    def test_job_url_construction(self):
        tenant, wd_server, site = "microsoft", "wd5", "External_Careers"
        external_path = "job/Redmond-WA/Cloud-Engineer_JR12345"
        expected = (
            "https://microsoft.wd5.myworkdayjobs.com/en-US/"
            "External_Careers/job/Redmond-WA/Cloud-Engineer_JR12345"
        )
        url = f"https://{tenant}.{wd_server}.myworkdayjobs.com/en-US/{site}/{external_path}"
        assert url == expected
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_workday.py -v
```
Expected: `ModuleNotFoundError: No module named 'sources.workday'`

- [ ] **Step 3: Create sources/workday.py**

```python
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_workday.py -v
```
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add sources/workday.py tests/test_workday.py
git commit -m "feat: add WorkdayAdapter — per-title searches with pagination and 429 backoff"
```

---

## Task 4: Update LinkedInIndeedAdapter with Workday discovery

**Files:**
- Modify: `sources/linkedin_indeed.py`
- Modify: `tests/test_linkedin_indeed.py`

- [ ] **Step 1: Write the failing test**

Add this class to `tests/test_linkedin_indeed.py`:

```python
import threading
import pandas as pd
from sources.linkedin_indeed import LinkedInIndeedAdapter


MOCK_DF_WITH_WORKDAY = pd.DataFrame([
    {
        "title": "Cloud Engineer",
        "company": "Microsoft",
        "location": "Redmond, WA",
        "description": "Cloud role with Azure",
        "job_url": "https://linkedin.com/jobs/123",
        "job_url_direct": "https://microsoft.wd5.myworkdayjobs.com/en-US/External_Careers/job/CE_JR1",
        "min_amount": None,
        "max_amount": None,
        "site": "linkedin",
        "date_posted": None,
    }
])


class TestWorkdayDiscovery:
    def test_scrape_one_discovers_workday_tenant(self):
        adapter = LinkedInIndeedAdapter(sites=["linkedin"])

        with patch("jobspy.scrape_jobs", return_value=MOCK_DF_WITH_WORKDAY):
            adapter._scrape_one("linkedin", "Cloud Engineer", "Seattle, WA")

        companies = adapter.discovered_workday_companies
        assert len(companies) == 1
        assert companies[0]["tenant"] == "microsoft"
        assert companies[0]["wd_server"] == "wd5"
        assert companies[0]["name"] == "Microsoft"

    def test_discovered_companies_deduplicates_across_calls(self):
        adapter = LinkedInIndeedAdapter(sites=["linkedin"])

        with patch("jobspy.scrape_jobs", return_value=MOCK_DF_WITH_WORKDAY):
            adapter._scrape_one("linkedin", "Cloud Engineer", "Seattle, WA")
            adapter._scrape_one("linkedin", "DevOps Engineer", "Seattle, WA")

        assert len(adapter.discovered_workday_companies) == 1

    def test_non_workday_urls_not_collected(self):
        adapter = LinkedInIndeedAdapter(sites=["linkedin"])
        df_no_workday = pd.DataFrame([{
            "title": "Cloud Engineer",
            "company": "Google",
            "location": "Remote",
            "description": "Cloud role",
            "job_url": "https://linkedin.com/jobs/999",
            "job_url_direct": "https://careers.google.com/jobs/results/123",
            "min_amount": None,
            "max_amount": None,
            "site": "linkedin",
            "date_posted": None,
        }])

        with patch("jobspy.scrape_jobs", return_value=df_no_workday):
            adapter._scrape_one("linkedin", "Cloud Engineer", "Remote")

        assert adapter.discovered_workday_companies == []
```

- [ ] **Step 2: Run the new tests to confirm they fail**

```bash
pytest tests/test_linkedin_indeed.py::TestWorkdayDiscovery -v
```
Expected: `AttributeError: 'LinkedInIndeedAdapter' object has no attribute 'discovered_workday_companies'`

- [ ] **Step 3: Update sources/linkedin_indeed.py**

Add `threading` import at the top:
```python
import threading
```

In `LinkedInIndeedAdapter.__init__`, add after `self.hours_old = ...`:
```python
        self._discovered: dict[str, dict] = {}
        self._lock = threading.Lock()
```

Add this property after `__init__`:
```python
    @property
    def discovered_workday_companies(self) -> list[dict]:
        return list(self._discovered.values())
```

In `_scrape_one`, inside the `for _, row in df.iterrows():` loop, add discovery inline — insert these lines just after `raw_company = _safe_str(row.get("company"))` and before `if not raw_title or not raw_company`:

```python
            # Passively discover Workday tenants from direct application URLs
            direct_url = _safe_str(row.get("job_url_direct"))
            if direct_url and "myworkdayjobs.com" in direct_url and raw_company:
                from sources.workday_discovery import extract_workday_tenant
                discovery = extract_workday_tenant(direct_url, raw_company)
                if discovery:
                    with self._lock:
                        self._discovered.setdefault(discovery["tenant"], discovery)
```

- [ ] **Step 4: Run the full linkedin test suite**

```bash
pytest tests/test_linkedin_indeed.py -v
```
Expected: all tests PASS (original + 3 new discovery tests).

- [ ] **Step 5: Commit**

```bash
git add sources/linkedin_indeed.py tests/test_linkedin_indeed.py
git commit -m "feat: discover Workday tenants from LinkedIn/Indeed job_url_direct field"
```

---

## Task 5: Build scripts/verify_workday_tokens.py

**Files:**
- Create: `scripts/verify_workday_tokens.py`

No tests for this script (it makes real HTTP calls). It is a dev tool, not pipeline code.

- [ ] **Step 1: Create scripts/ directory if needed**

```bash
mkdir -p scripts
```

- [ ] **Step 2: Create scripts/verify_workday_tokens.py**

```python
#!/usr/bin/env python
"""Verify Workday career board configs and print ready-to-paste YAML.

Usage:
  # Validate all workday: entries in target_companies.yaml
  python scripts/verify_workday_tokens.py

  # Parse and validate one or more careers-page URLs
  python scripts/verify_workday_tokens.py https://crowdstrike.wd5.myworkdayjobs.com/CrowdStrikeCareers
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import aiohttp
import yaml

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from sources.workday_discovery import extract_workday_tenant

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
}


async def check_company(session: aiohttp.ClientSession, entry: dict) -> None:
    tenant = entry["tenant"]
    wd_server = entry["wd_server"]
    site = entry["site"]
    name = entry.get("name", tenant)
    url = (
        f"https://{tenant}.{wd_server}.myworkdayjobs.com"
        f"/wday/cxs/{tenant}/{site}/jobs"
    )
    body = {"searchText": "engineer", "limit": 1, "offset": 0, "appliedFacets": {}}

    try:
        async with session.post(
            url, json=body, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                total = data.get("total", 0)
                print(f"  OK  {name:30s}  {total:>5d} jobs  (tenant={tenant}, {wd_server}, site={site})")
                print(f"       YAML block:")
                print(f"         - tenant: {tenant}")
                print(f"           wd_server: {wd_server}")
                print(f"           site: {site}")
                print(f"           name: {name}")
            else:
                print(f" FAIL {name:30s}  HTTP {resp.status}  ({url})")
    except Exception as e:
        print(f" FAIL {name:30s}  {e}")


async def main(args: list[str]) -> None:
    async with aiohttp.ClientSession(headers=_HEADERS) as session:
        if args:
            # Validate URLs passed as arguments
            for raw_url in args:
                company_name = raw_url.split(".")[0].replace("https://", "").capitalize()
                entry = extract_workday_tenant(raw_url, company_name)
                if not entry:
                    print(f" SKIP {raw_url}  — could not parse as Workday URL")
                    continue
                await check_company(session, entry)
        else:
            # Validate all existing workday: entries in target_companies.yaml
            data = yaml.safe_load(Path("target_companies.yaml").read_text()) or {}
            companies = data.get("workday", [])
            if not companies:
                print("No workday: entries found in target_companies.yaml")
                return
            print(f"Checking {len(companies)} Workday entries...\n")
            tasks = [check_company(session, c) for c in companies]
            await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
```

- [ ] **Step 3: Run against a known Workday URL to confirm it works**

```bash
python scripts/verify_workday_tokens.py https://zoom.wd5.myworkdayjobs.com/Zoom
```
Expected output: `  OK  Zoom   ...  jobs  (tenant=zoom, wd5, site=Zoom)` followed by YAML block.

- [ ] **Step 4: Commit**

```bash
git add scripts/verify_workday_tokens.py
git commit -m "feat: add verify_workday_tokens.py script for discovering and validating Workday boards"
```

---

## Task 6: Verify and seed target_companies.yaml

**Files:**
- Modify: `target_companies.yaml`

- [ ] **Step 1: Run the verify script against all 12 candidate companies**

Run each URL through the script to confirm tenant/wd_server/site. Visit each company's careers page if needed to get the exact URL.

```bash
python scripts/verify_workday_tokens.py \
  https://microsoft.wd5.myworkdayjobs.com/External_Careers \
  https://salesforce.wd12.myworkdayjobs.com/External_Career_Site \
  https://servicenow.wd5.myworkdayjobs.com/External \
  https://crowdstrike.wd5.myworkdayjobs.com/CrowdStrikeCareers \
  https://paloaltonetworks.wd1.myworkdayjobs.com/External \
  https://okta.wd5.myworkdayjobs.com/okta \
  https://cisco.wd5.myworkdayjobs.com/Cisco \
  https://adobe.wd5.myworkdayjobs.com/External \
  https://zoom.wd5.myworkdayjobs.com/Zoom \
  https://splunk.wd5.myworkdayjobs.com/External \
  https://workday.wd5.myworkdayjobs.com/Workday \
  https://box.wd5.myworkdayjobs.com/Box_External_Career_Site
```

Note: If a URL returns FAIL, visit `{company}.com/careers` in a browser, copy the URL from the address bar, and re-run with the corrected URL.

- [ ] **Step 2: Add verified workday: section to target_companies.yaml**

Append the following to `target_companies.yaml` using the YAML blocks printed by the verify script in Step 1. Use the exact values the script confirms — do not copy the template below verbatim if the script showed different values:

```yaml
workday:
  # Verified YYYY-MM-DD — replace with output from verify_workday_tokens.py
  # ── Security ────────────────────────────────────────────────
  - tenant: crowdstrike
    wd_server: wd5
    site: CrowdStrikeCareers
    name: CrowdStrike
  - tenant: paloaltonetworks
    wd_server: wd1
    site: External
    name: Palo Alto Networks
  - tenant: okta
    wd_server: wd5
    site: okta
    name: Okta
  - tenant: splunk
    wd_server: wd5
    site: External
    name: Splunk

  # ── Cloud / Platform ────────────────────────────────────────
  - tenant: microsoft
    wd_server: wd5
    site: External_Careers
    name: Microsoft
  - tenant: servicenow
    wd_server: wd5
    site: External
    name: ServiceNow
  - tenant: cisco
    wd_server: wd5
    site: Cisco
    name: Cisco

  # ── Big Tech / SaaS ─────────────────────────────────────────
  - tenant: salesforce
    wd_server: wd12
    site: External_Career_Site
    name: Salesforce
  - tenant: adobe
    wd_server: wd5
    site: External
    name: Adobe
  - tenant: zoom
    wd_server: wd5
    site: Zoom
    name: Zoom
  - tenant: workday
    wd_server: wd5
    site: Workday
    name: Workday
  - tenant: box
    wd_server: wd5
    site: Box_External_Career_Site
    name: Box
```

- [ ] **Step 3: Run verify script against the yaml to confirm all entries are live**

```bash
python scripts/verify_workday_tokens.py
```
Expected: all 12 entries print OK with non-zero job counts. Fix any FAIL entries by updating the wd_server or site slug.

- [ ] **Step 4: Commit**

```bash
git add target_companies.yaml
git commit -m "feat: seed target_companies.yaml with 12 verified Workday H-1B sponsors"
```

---

## Task 7: Wire WorkdayAdapter and discovery into main.py

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add imports to main.py**

Add these two imports alongside the existing source imports (around line 40–46):
```python
from sources.workday import WorkdayAdapter
from sources.workday_discovery import save_new_companies
```

- [ ] **Step 2: Update build_adapters() signature and body**

Replace the existing `build_adapters` function with:

```python
def build_adapters(
    companies: dict,
) -> tuple[list, list[tuple[str, str]], LinkedInIndeedAdapter]:
    """Returns (adapters, display_sources, li_adapter).

    li_adapter is returned separately so run_pipeline can read
    discovered_workday_companies from it after scraping completes.
    """
    adapters = []
    display: list[tuple[str, str]] = []

    gh = companies.get("greenhouse", [])
    if gh:
        adapters.append(GreenhouseAdapter(companies=gh))
        display.append(("greenhouse", f"Greenhouse ({len(gh)} co)"))

    lv = companies.get("lever", [])
    if lv:
        adapters.append(LeverAdapter(companies=lv))
        display.append(("lever", f"Lever ({len(lv)} co)"))

    ab = companies.get("ashby", [])
    if ab:
        adapters.append(AshbyAdapter(companies=ab))
        display.append(("ashby", f"Ashby ({len(ab)} co)"))

    li_adapter = LinkedInIndeedAdapter()
    adapters.append(li_adapter)
    display.append(("linkedin_indeed", "LinkedIn + Indeed + Google"))

    adapters.append(HackerNewsAdapter())
    display.append(("hackernews", "HackerNews (Who is Hiring)"))

    adapters.append(RemoteOKAdapter())
    display.append(("remoteok", "RemoteOK"))

    wd = companies.get("workday", [])
    if wd:
        adapters.append(WorkdayAdapter(companies=wd))
        display.append(("workday", f"Workday ({len(wd)} co)"))

    return adapters, display, li_adapter
```

Also add `LinkedInIndeedAdapter` to the import at the top of `main.py` if not already there — it's already imported via `from sources.linkedin_indeed import LinkedInIndeedAdapter`.

- [ ] **Step 3: Update the call site in run_pipeline to unpack the 3-tuple**

Find this line (around line 130):
```python
    adapters, display_sources = build_adapters(companies)
```
Replace with:
```python
    adapters, display_sources, li_adapter = build_adapters(companies)
```

- [ ] **Step 4: Add discovery save after Phase 3**

Find the block ending Phase 3 (after the `with ui.scrape_table(...)` block closes). It looks like:
```python
    all_scraped = scrape_result.jobs
    ui.phase_done(f"{len(all_scraped)} unique jobs after cross-source + DB dedup")
```

Add immediately after `ui.phase_done(...)`:
```python
    # Persist any newly discovered Workday companies for the next run
    new_wd = save_new_companies(
        li_adapter.discovered_workday_companies,
        yaml_path="target_companies.yaml",
    )
    if new_wd:
        logger.info(
            f"Discovered {new_wd} new Workday "
            f"{'company' if new_wd == 1 else 'companies'} — "
            f"added to target_companies.yaml for next run"
        )
```

- [ ] **Step 5: Run the full test suite**

```bash
pytest tests/ -v
```
Expected: all tests PASS. The `build_adapters` change is not unit-tested directly (it's a wiring function), but all adapter and discovery tests should pass.

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "feat: wire WorkdayAdapter and auto-discovery into pipeline"
```

---

## Task 8: Full integration smoke test

**Files:** none (read-only verification)

- [ ] **Step 1: Run the full test suite one final time**

```bash
pytest tests/ -v --tb=short
```
Expected: all tests PASS, zero failures.

- [ ] **Step 2: Verify imports are clean (no circular imports)**

```bash
python -c "from sources.workday import WorkdayAdapter; print('OK')"
python -c "from sources.workday_discovery import extract_workday_tenant, save_new_companies; print('OK')"
python -c "import main; print('OK')"
```
Expected: each prints `OK` with no errors.

- [ ] **Step 3: Verify the verify script runs against the seeded yaml**

```bash
python scripts/verify_workday_tokens.py
```
Expected: all 12 seeded companies print OK with non-zero job counts.

- [ ] **Step 4: Final commit if any cleanup was needed, otherwise done**

```bash
git status
```
If any files were incidentally modified, commit them now. Otherwise the feature is complete.

---

## Self-Review Notes

- **Spec coverage:**
  - WorkdayAdapter with per-title search and pagination ✓ (Task 3)
  - 1.5s delay between titles within a company ✓ (`_REQUEST_DELAY`, Task 3)
  - 429 exponential backoff ✓ (`_post_with_retry`, Task 3)
  - Passive discovery from `job_url_direct` ✓ (Task 4)
  - `save_new_companies` persists to yaml ✓ (Task 2)
  - `build_adapters()` returns `LinkedInIndeedAdapter` reference ✓ (Task 7)
  - Discovery save after Phase 3 in `main.py` ✓ (Task 7)
  - Seed 12 verified companies in `target_companies.yaml` ✓ (Task 6)
  - `verify_workday_tokens.py` script ✓ (Task 5)
  - `ruamel.yaml` added to `requirements.txt` ✓ (Task 1)
  - All error cases from spec error table covered ✓ (Tasks 2, 3)

- **Type consistency:** `extract_workday_tenant` returns `dict | None` throughout. `save_new_companies` takes `list[dict]` throughout. `_scrape_company` returns `tuple[list[RawJob], list[str]]` and `_post_with_retry` returns `tuple[dict, str | None]` — consistent across tasks.

- **No placeholders:** All steps contain actual code.
