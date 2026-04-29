# Description Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-fetch job descriptions from URLs when scrapers return empty descriptions, then surface remaining no-desc jobs in the Daily tab instead of silently dropping them.

**Architecture:** A new `sources/backfill.py` module runs between scraping and screening. It fetches each description-less job's URL with aiohttp + BeautifulSoup, extracts page text, and patches the RawJob. `main.py` partitions jobs into has-desc (normal pipeline) and still-no-desc (bypass screening, surface in Daily at confidence=1). `generate_materials.py` gets a last-chance fetch fallback.

**Tech Stack:** aiohttp, beautifulsoup4 (both already in requirements.txt), asyncio, SQLite

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `sources/backfill.py` | Async URL fetcher — backfill missing descriptions |
| Create | `tests/test_backfill.py` | Unit tests for backfill module |
| Modify | `db/database.py:181-186` | Add `update_description()` and `get_url_by_fingerprint()` |
| Modify | `tests/test_database.py` | Tests for new DB methods |
| Modify | `main.py:121-235` | Integrate backfill step, partition no-desc jobs, update summary |
| Modify | `generate_materials.py:73-74` | Fallback URL fetch when description empty at generation time |

**Not modified:** `screening/stage1.py` (keep no-desc rejection as safety net), `models/job.py`, `config.py`, `sheets/daily.py` (no-desc jobs are regular ScreenedJob objects, just with confidence=1).

---

### Task 1: Create `sources/backfill.py` — core backfill module

**Files:**
- Create: `sources/backfill.py`
- Create: `tests/test_backfill.py`

- [ ] **Step 1: Write the test file**

```python
# tests/test_backfill.py
import pytest
import aiohttp
from unittest.mock import AsyncMock, patch, MagicMock
from models.job import RawJob
from sources.backfill import backfill_descriptions, extract_description_from_html


def make_job(**kwargs) -> RawJob:
    defaults = {
        "title": "Cloud Engineer",
        "company": "TestCo",
        "location": "Remote",
        "description": None,
        "url": "https://jobs.example.com/cloud-engineer",
        "source": "linkedin",
    }
    defaults.update(kwargs)
    return RawJob(**defaults)


SAMPLE_HTML = """
<html>
<head><title>Cloud Engineer</title></head>
<body>
<nav>Site nav</nav>
<script>var x = 1;</script>
<style>.foo { color: red; }</style>
<div class="job-description">
  <h1>Cloud Engineer</h1>
  <p>We are looking for a cloud engineer with AWS and Kubernetes experience.</p>
  <p>Requirements: 2+ years, Python, Terraform.</p>
</div>
<footer>Copyright 2026</footer>
</body>
</html>
"""


class TestExtractDescription:
    def test_extracts_text_removes_scripts_and_nav(self):
        text = extract_description_from_html(SAMPLE_HTML)
        assert "cloud engineer" in text.lower()
        assert "aws" in text.lower()
        assert "var x" not in text  # script removed
        assert "Site nav" not in text  # nav removed
        assert "Copyright" not in text  # footer removed

    def test_returns_none_for_empty_html(self):
        assert extract_description_from_html("") is None
        assert extract_description_from_html("<html><body></body></html>") is None

    def test_returns_none_for_short_text(self):
        # Less than 50 chars of meaningful text = not a real description
        assert extract_description_from_html("<html><body><p>Hi</p></body></html>") is None


class TestBackfillDescriptions:
    @pytest.mark.asyncio
    async def test_skips_jobs_with_existing_description(self):
        jobs = [make_job(description="Already has a description")]
        result = await backfill_descriptions(jobs, delay=0)
        assert result.skipped == 1
        assert result.filled == 0
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_skips_jobs_with_no_url(self):
        jobs = [make_job(url="")]
        result = await backfill_descriptions(jobs, delay=0)
        assert result.skipped == 1
        assert result.filled == 0

    @pytest.mark.asyncio
    async def test_fills_description_from_url(self):
        jobs = [make_job()]

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value=SAMPLE_HTML)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("sources.backfill.aiohttp.ClientSession", return_value=mock_session):
            result = await backfill_descriptions(jobs, delay=0)

        assert result.filled == 1
        assert jobs[0].description is not None
        assert "cloud engineer" in jobs[0].description.lower()

    @pytest.mark.asyncio
    async def test_handles_http_error_gracefully(self):
        jobs = [make_job()]

        mock_resp = AsyncMock()
        mock_resp.status = 403
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("sources.backfill.aiohttp.ClientSession", return_value=mock_session):
            result = await backfill_descriptions(jobs, delay=0)

        assert result.failed == 1
        assert jobs[0].description is None

    @pytest.mark.asyncio
    async def test_caps_description_length(self):
        long_text = "word " * 2000  # ~10000 chars
        long_html = f"<html><body><div>{long_text}</div></body></html>"
        jobs = [make_job()]

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value=long_html)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("sources.backfill.aiohttp.ClientSession", return_value=mock_session):
            result = await backfill_descriptions(jobs, delay=0)

        assert result.filled == 1
        assert len(jobs[0].description) <= 5000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_backfill.py -v`
Expected: ImportError — `sources.backfill` does not exist yet.

- [ ] **Step 3: Implement `sources/backfill.py`**

```python
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

    logger.info(f"Backfill: {filled} filled, {failed} failed, {skipped} already had descriptions")
    return BackfillResult(filled=filled, failed=failed, skipped=skipped)


async def fetch_description_from_url(url: str, timeout: float = 15.0) -> str | None:
    """One-shot fetch for a single URL. Used by generate_materials fallback."""
    async with aiohttp.ClientSession() as session:
        return await _fetch_one(session, url, timeout)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_backfill.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add sources/backfill.py tests/test_backfill.py
git commit -m "feat: add URL-based description backfill module"
```

---

### Task 2: Add `update_description()` and `get_url_by_fingerprint()` to Database

**Files:**
- Modify: `db/database.py`
- Modify: `tests/test_database.py`

- [ ] **Step 1: Write failing tests**

Add to the end of `tests/test_database.py`:

```python
    def test_update_description(self, db):
        job = RawJob(
            title="SRE", company="Meta", location="NYC",
            description=None,
            url="https://example.com/sre",
            source="linkedin",
        )
        db.save_jobs([job])
        assert db.get_description_by_fingerprint("meta||sre") is None

        db.update_description("meta||sre", "Updated job description text")
        assert db.get_description_by_fingerprint("meta||sre") == "Updated job description text"

    def test_get_url_by_fingerprint(self, db):
        job = RawJob(
            title="DevOps", company="Google", location="SF",
            url="https://example.com/devops",
            source="indeed",
        )
        db.save_jobs([job])
        assert db.get_url_by_fingerprint("google||devops") == "https://example.com/devops"
        assert db.get_url_by_fingerprint("unknown||job") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_database.py::TestDatabase::test_update_description tests/test_database.py::TestDatabase::test_get_url_by_fingerprint -v`
Expected: AttributeError — methods don't exist yet.

- [ ] **Step 3: Implement the two methods**

Add to `db/database.py` after the existing `get_description_by_fingerprint` method (after line 186):

```python
    def update_description(self, fingerprint: str, description: str) -> None:
        """Update the description for a job identified by fingerprint."""
        self.conn.execute(
            "UPDATE jobs SET description = ? WHERE fingerprint = ?",
            (description, fingerprint),
        )
        self.conn.commit()

    def get_url_by_fingerprint(self, fingerprint: str) -> str | None:
        """Get the URL for a job identified by fingerprint."""
        cursor = self.conn.execute(
            "SELECT url FROM jobs WHERE fingerprint = ?", (fingerprint,)
        )
        row = cursor.fetchone()
        return row["url"] if row else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_database.py -v`
Expected: All tests PASS (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add db/database.py tests/test_database.py
git commit -m "feat: add update_description and get_url_by_fingerprint to Database"
```

---

### Task 3: Integrate backfill into `main.py` pipeline

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add imports**

At the top of `main.py`, add to the import block (after the `from sources.orchestrator` import, around line 37):

```python
from sources.backfill import backfill_descriptions
```

- [ ] **Step 2: Add backfill step and partition logic after scraping**

Replace `main.py` lines 157-164 (from `unique_jobs = scrape_result.jobs` through `db.save_jobs(unique_jobs)`) with:

```python
    unique_jobs = scrape_result.jobs

    # -- Backfill missing descriptions from URLs --
    backfill_result = await backfill_descriptions(unique_jobs)

    # Partition: jobs with descriptions go through screening pipeline,
    # jobs still missing descriptions bypass screening and go to Daily at low confidence
    desc_jobs = [j for j in unique_jobs if j.description and j.description.strip()]
    no_desc_jobs = [j for j in unique_jobs if not (j.description and j.description.strip())]

    # -- Stage 1: Regex filter (only jobs with descriptions) --
    stage1 = Stage1Filter()
    passed_jobs, rejected = stage1.filter_batch(desc_jobs)

    # Save all jobs to SQLite (including backfilled descriptions)
    db.save_jobs(unique_jobs)

    # Update descriptions in SQLite for jobs that were backfilled
    # (save_jobs uses INSERT OR IGNORE, so if the job already existed
    # from a prior run, the backfilled description won't be saved.
    # Explicitly update those.)
    for job in unique_jobs:
        if job.description and job.description.strip():
            db.update_description(job.fingerprint, job.description)
```

- [ ] **Step 3: Create synthetic ScreenedJobs for no-desc jobs and merge into Daily output**

Replace `main.py` lines 208-213 (the daily_jobs block) with:

```python
    # -- Build Daily tab: screened APPLY/MAYBE + no-desc jobs for manual review --
    daily_jobs = [
        j for j in screened_jobs
        if j.verdict in (ScreeningVerdict.APPLY, ScreeningVerdict.MAYBE)
    ]

    # No-desc jobs bypass screening — surface them for manual review
    for job in no_desc_jobs:
        daily_jobs.append(ScreenedJob(
            title=job.title,
            company=job.company,
            location=job.location,
            description=job.description,
            salary_min=job.salary_min,
            salary_max=job.salary_max,
            url=job.url,
            source=job.source,
            scraped_at=job.scraped_at,
            verdict=ScreeningVerdict.MAYBE,
            confidence=1,
            reasoning="No JD available — review link manually",
            match_signals=[],
            risk_flags=["no_description"],
            suggested_angle="",
        ))

    daily_ops.write_screened_jobs(daily_ws, daily_jobs)
```

- [ ] **Step 4: Update `print_summary` to include backfill stats**

Update the `print_summary` function signature (line 94) to accept backfill stats:

```python
def print_summary(
    total_scraped: int, dupes: int, stage1_passed: int, stage1_rejected: int,
    stage2_results: list[ScreenedJob], errors: list[str],
    backfill_filled: int = 0, backfill_failed: int = 0,
    no_desc_surfaced: int = 0,
) -> None:
```

Add after the `Duplicates removed` line (after line 107):

```python
    print(f"\n  DESCRIPTION BACKFILL")
    print(f"  Filled from URL:  {backfill_filled}")
    print(f"  Still missing:    {backfill_failed}")
    if no_desc_surfaced:
        print(f"  Surfaced in Daily (no JD): {no_desc_surfaced}")
```

Update the `print_summary` call at the bottom (lines 228-235) to pass the new args:

```python
    print_summary(
        total_scraped=len(unique_jobs),
        dupes=0,
        stage1_passed=len(passed_jobs),
        stage1_rejected=len(rejected),
        stage2_results=screened_jobs,
        errors=scrape_result.errors,
        backfill_filled=backfill_result.filled,
        backfill_failed=backfill_result.failed,
        no_desc_surfaced=len(no_desc_jobs),
    )
```

- [ ] **Step 5: Run type check**

Run: `python -m py_compile main.py`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "feat: integrate description backfill into pipeline, surface no-desc jobs in Daily"
```

---

### Task 4: Add fallback fetch in `generate_materials.py`

**Files:**
- Modify: `generate_materials.py`

- [ ] **Step 1: Add imports**

At the top of `generate_materials.py`, add after the existing imports (around line 12):

```python
import asyncio
from sources.backfill import fetch_description_from_url
```

- [ ] **Step 2: Add fallback fetch when description is empty**

Replace `generate_materials.py` lines 73-74:

```python
        fingerprint = f"{company.strip().lower()}||{title.strip().lower()}"
        description = db.get_description_by_fingerprint(fingerprint) or ""
```

With:

```python
        fingerprint = f"{company.strip().lower()}||{title.strip().lower()}"
        description = db.get_description_by_fingerprint(fingerprint) or ""

        # Fallback: if no description in DB, try fetching from the job URL
        if not description.strip() and apply_link.strip():
            logger.info(f"  No description in DB — attempting URL fetch for {company}")
            fetched = asyncio.run(fetch_description_from_url(apply_link))
            if fetched:
                description = fetched
                db.update_description(fingerprint, description)
                logger.info(f"  Fetched description from URL ({len(description)} chars)")
            else:
                logger.warning(f"  Could not fetch description from URL — resume will be less tailored")
```

- [ ] **Step 3: Run type check**

Run: `python -m py_compile generate_materials.py`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add generate_materials.py
git commit -m "feat: fallback URL fetch in generate_materials when description missing"
```

---

### Task 5: Run full test suite and verify

**Files:** (no changes — validation only)

- [ ] **Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests pass. The existing `test_rejects_empty_description` in `test_stage1.py` still passes (Stage 1 still rejects no-desc jobs as a safety net; we just don't send them there in main.py).

- [ ] **Step 2: Run type checks on all modified files**

Run: `python -m py_compile main.py generate_materials.py sources/backfill.py db/database.py`
Expected: No errors.

- [ ] **Step 3: Final commit (if any fixups needed)**

```bash
git add -A
git commit -m "fix: address test/type-check issues from backfill integration"
```
