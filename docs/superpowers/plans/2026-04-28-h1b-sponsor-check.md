# H1B Sponsor Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Phase 7 to the pipeline that checks companies from open sources (LinkedIn, Indeed, HackerNews, RemoteOK, Workday) against h1bdata.info for recent H1B filing history, caching results in SQLite, and surfacing `no_h1b_history` risk flags in Stage 2 and the Daily tab.

**Architecture:** A new `H1BChecker` class in `screening/h1b_checker.py` mutates `h1b_sponsor_verified` on `RawJob` objects in-place. It checks SQLite cache first (30-day TTL), then scrapes h1bdata.info concurrently (semaphore=3) for cache misses. Stage 2 receives the field in the job JSON prompt and adds the risk flag and confidence penalty; fallback paths in `_default_apply`/`_default_maybe` inject the flag directly from the field.

**Tech Stack:** aiohttp (already a dependency), Python stdlib `re`/`html`/`urllib.parse`, SQLite (via existing Database class), pytest + pytest-asyncio (already used in tests)

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `config.py` | Add `H1B_CACHE_TTL_DAYS = 30` |
| Modify | `models/job.py` | Add `h1b_sponsor_verified: bool \| None = None` to `RawJob` |
| Modify | `db/database.py` | Add `h1b_sponsor_cache` table + `get_h1b_cache` / `set_h1b_cache` methods |
| Create | `screening/h1b_checker.py` | `H1BChecker` class — normalize, scrape, cache, mutate |
| Create | `tests/test_h1b_checker.py` | All tests for DB cache, normalization, scraping, check_batch |
| Modify | `prompts/screening.md` | Add `h1b_sponsor_verified` field to job JSON + verdict guidance |
| Modify | `screening/stage2.py` | Include field in job data; inject flag in fallback paths |
| Modify | `main.py` | Insert Phase 7, bump `TOTAL_PHASES` to 10, renumber phases |

---

## Task 1: Config constant + RawJob field

**Files:**
- Modify: `config.py`
- Modify: `models/job.py`

- [ ] **Step 1: Write a failing test**

Add this test to `tests/test_config.py` inside the `TestConfig` class:

```python
def test_h1b_cache_ttl_exists(self):
    from config import H1B_CACHE_TTL_DAYS
    assert H1B_CACHE_TTL_DAYS == 30
```

Run: `pytest tests/test_config.py::TestConfig::test_h1b_cache_ttl_exists -v`
Expected: FAIL — `ImportError: cannot import name 'H1B_CACHE_TTL_DAYS'`

- [ ] **Step 2: Add the constant to config.py**

In `config.py`, after the `SCREENING_BATCH_SIZE` line (currently line 186), add:

```python
H1B_CACHE_TTL_DAYS = 30         # Days before re-checking a company on h1bdata.info
```

Run: `pytest tests/test_config.py::TestConfig::test_h1b_cache_ttl_exists -v`
Expected: PASS

- [ ] **Step 3: Write a failing test for the RawJob field**

Create a new file `tests/test_h1b_checker.py` with:

```python
"""Tests for H1B sponsor check — DB cache, normalization, scraping, check_batch."""
from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from db.database import Database
from models.job import RawJob


def _make_db() -> Database:
    db = Database(":memory:")
    db.initialize()
    return db


def _make_job(company: str, source: str = "linkedin") -> RawJob:
    return RawJob(
        title="Cloud Engineer",
        company=company,
        location="Remote",
        url="https://example.com/job",
        source=source,
        description="We use AWS and Kubernetes.",
    )


class TestRawJobH1BField(unittest.TestCase):
    def test_field_defaults_to_none(self):
        job = _make_job("Stripe")
        assert job.h1b_sponsor_verified is None

    def test_field_can_be_set_true(self):
        job = _make_job("Stripe")
        job.h1b_sponsor_verified = True
        assert job.h1b_sponsor_verified is True

    def test_field_can_be_set_false(self):
        job = _make_job("Stripe")
        job.h1b_sponsor_verified = False
        assert job.h1b_sponsor_verified is False
```

Run: `pytest tests/test_h1b_checker.py::TestRawJobH1BField -v`
Expected: FAIL — `ValidationError` or attribute error because the field doesn't exist yet.

- [ ] **Step 4: Add the field to RawJob**

In `models/job.py`, add after the `posted_at` line (currently line 28):

```python
h1b_sponsor_verified: bool | None = None  # None = not checked / curated source
```

Run: `pytest tests/test_h1b_checker.py::TestRawJobH1BField -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Confirm existing tests still pass**

Run: `pytest tests/ -v`
Expected: All previously passing tests still PASS. The new field has a default so no existing `RawJob` construction breaks.

- [ ] **Step 6: Commit**

```bash
git add config.py models/job.py tests/test_h1b_checker.py tests/test_config.py
git commit -m "feat: add H1B_CACHE_TTL_DAYS config constant and h1b_sponsor_verified field on RawJob"
```

---

## Task 2: Database cache table + methods

**Files:**
- Modify: `db/database.py`
- Modify: `tests/test_h1b_checker.py`

- [ ] **Step 1: Write failing tests for the DB cache**

Add this class to `tests/test_h1b_checker.py`:

```python
class TestH1BCacheDB(unittest.TestCase):
    def test_get_returns_none_on_miss(self):
        db = _make_db()
        assert db.get_h1b_cache("stripe") is None

    def test_set_then_get_returns_bool(self):
        db = _make_db()
        db.set_h1b_cache("stripe", "Stripe, Inc.", True)
        assert db.get_h1b_cache("stripe") is True

    def test_set_false_then_get_returns_false(self):
        db = _make_db()
        db.set_h1b_cache("nosponsco", "NoSponsCo", False)
        assert db.get_h1b_cache("nosponsco") is False

    def test_get_returns_none_when_expired(self):
        db = _make_db()
        old_ts = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        db.conn.execute(
            "INSERT INTO h1b_sponsor_cache (company_key, company_raw, verified, checked_at)"
            " VALUES (?, ?, ?, ?)",
            ("oldco", "OldCo", 1, old_ts),
        )
        db.conn.commit()
        assert db.get_h1b_cache("oldco") is None

    def test_upsert_overwrites_expired(self):
        db = _make_db()
        old_ts = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        db.conn.execute(
            "INSERT INTO h1b_sponsor_cache (company_key, company_raw, verified, checked_at)"
            " VALUES (?, ?, ?, ?)",
            ("stripe", "Stripe", 0, old_ts),
        )
        db.conn.commit()
        db.set_h1b_cache("stripe", "Stripe", True)
        assert db.get_h1b_cache("stripe") is True
```

Run: `pytest tests/test_h1b_checker.py::TestH1BCacheDB -v`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'get_h1b_cache'`

- [ ] **Step 2: Add the cache table to _create_tables()**

In `db/database.py`, append to the SQL string inside `_create_tables()` (after the last `CREATE TABLE` block):

```python
            CREATE TABLE IF NOT EXISTS h1b_sponsor_cache (
                company_key  TEXT PRIMARY KEY,
                company_raw  TEXT NOT NULL,
                verified     INTEGER NOT NULL,
                checked_at   TEXT NOT NULL
            );
```

- [ ] **Step 3: Add get_h1b_cache and set_h1b_cache methods**

In `db/database.py`, update the top import line from:
```python
from datetime import datetime
```
to:
```python
from datetime import datetime, timezone
```

Then add these two methods to the `Database` class (after the existing `save_audit_entries_bulk` method):

```python
def get_h1b_cache(self, company_key: str) -> bool | None:
    """Return cached verified bool if fresh (within TTL), else None."""
    from config import H1B_CACHE_TTL_DAYS
    row = self.conn.execute(
        "SELECT verified, checked_at FROM h1b_sponsor_cache WHERE company_key = ?",
        (company_key,),
    ).fetchone()
    if row is None:
        return None
    checked = datetime.fromisoformat(row["checked_at"])
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - checked).days
    if age_days >= H1B_CACHE_TTL_DAYS:
        return None
    return bool(row["verified"])

def set_h1b_cache(self, company_key: str, company_raw: str, verified: bool) -> None:
    """Upsert a sponsor check result. Only call with definitive True/False, not None."""
    now = datetime.now(timezone.utc).isoformat()
    self.conn.execute(
        """INSERT OR REPLACE INTO h1b_sponsor_cache
               (company_key, company_raw, verified, checked_at)
               VALUES (?, ?, ?, ?)""",
        (company_key, company_raw, int(verified), now),
    )
    self.conn.commit()
```

Run: `pytest tests/test_h1b_checker.py::TestH1BCacheDB -v`
Expected: PASS (5 tests)

- [ ] **Step 4: Confirm full test suite passes**

Run: `pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add db/database.py tests/test_h1b_checker.py
git commit -m "feat: add h1b_sponsor_cache table and get/set methods to Database"
```

---

## Task 3: H1BChecker — normalization and HTML parsing

**Files:**
- Create: `screening/h1b_checker.py`
- Modify: `tests/test_h1b_checker.py`

- [ ] **Step 1: Write failing tests for normalization and HTML parsing**

Add this class to `tests/test_h1b_checker.py`:

```python
class TestH1BCheckerNormalize(unittest.TestCase):
    def test_strips_inc_suffix(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker._normalize("Stripe, Inc.") == "stripe"

    def test_strips_llc_suffix(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker._normalize("Meta Platforms LLC") == "meta platforms"

    def test_no_suffix(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker._normalize("ServiceNow") == "servicenow"

    def test_strips_corp(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker._normalize("Oracle Corp") == "oracle"

    def test_strips_limited(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker._normalize("Tata Consultancy Services Limited") == "tata consultancy services"

    def test_collapses_extra_whitespace(self):
        from screening.h1b_checker import H1BChecker
        assert H1BChecker._normalize("  Google  LLC  ") == "google"


class TestH1BCheckerHasResults(unittest.TestCase):
    def test_no_data_string_returns_false(self):
        from screening.h1b_checker import H1BChecker
        html = "<html><body><table><tbody>No data available in table</tbody></table></body></html>"
        assert H1BChecker._has_results(html) is False

    def test_tbody_with_tr_returns_true(self):
        from screening.h1b_checker import H1BChecker
        html = "<html><body><table><tbody><tr><td>STRIPE INC</td></tr></tbody></table></body></html>"
        assert H1BChecker._has_results(html) is True

    def test_empty_tbody_returns_false(self):
        from screening.h1b_checker import H1BChecker
        html = "<html><body><table><tbody></tbody></table></body></html>"
        assert H1BChecker._has_results(html) is False
```

Run: `pytest tests/test_h1b_checker.py::TestH1BCheckerNormalize tests/test_h1b_checker.py::TestH1BCheckerHasResults -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'screening.h1b_checker'`

- [ ] **Step 2: Create screening/h1b_checker.py with normalize and _has_results**

Create `screening/h1b_checker.py`:

```python
"""H1B sponsor check via h1bdata.info — Phase 7 of the pipeline."""
from __future__ import annotations

import asyncio
import re
import urllib.parse
from datetime import datetime, timezone

import aiohttp

from db.database import Database
from models.job import RawJob

_LEGAL_SUFFIXES_RE = re.compile(
    r"\b(inc|llc|corp|ltd|l\.?p|plc|incorporated|limited|corporation)\b\.?",
    re.IGNORECASE,
)

_CURATED_PREFIXES = ("greenhouse-", "lever-", "ashby-")


class H1BChecker:
    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _normalize(company: str) -> str:
        """Return a canonical cache key for a company name."""
        name = _LEGAL_SUFFIXES_RE.sub("", company)
        name = re.sub(r"[^a-z0-9\s]", "", name.lower())
        return re.sub(r"\s+", " ", name).strip()

    @staticmethod
    def _has_results(html: str) -> bool:
        """Return True if the h1bdata.info HTML table contains at least one data row."""
        if "no data available in table" in html.lower():
            return False
        return bool(re.search(r"<tbody[^>]*>\s*<tr", html, re.IGNORECASE))
```

Run: `pytest tests/test_h1b_checker.py::TestH1BCheckerNormalize tests/test_h1b_checker.py::TestH1BCheckerHasResults -v`
Expected: PASS (9 tests)

- [ ] **Step 3: Commit**

```bash
git add screening/h1b_checker.py tests/test_h1b_checker.py
git commit -m "feat: add H1BChecker skeleton with _normalize and _has_results"
```

---

## Task 4: H1BChecker — scraping methods

**Files:**
- Modify: `screening/h1b_checker.py`
- Modify: `tests/test_h1b_checker.py`

- [ ] **Step 1: Write failing tests for _scrape_year and _check_company**

Add this helper function and test class to `tests/test_h1b_checker.py` (after the existing import block, before the test classes):

```python
def _mock_session(html_by_year: dict[int, str]):
    """Return a mock aiohttp.ClientSession whose get() returns HTML keyed by year."""

    def make_resp(html: str):
        resp = MagicMock()
        resp.text = AsyncMock(return_value=html)
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=None)
        return resp

    def get(url, **kwargs):
        for year, html in html_by_year.items():
            if str(year) in url:
                return make_resp(html)
        return make_resp("<html></html>")

    session = MagicMock()
    session.get = get
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session
```

Then add:

```python
class TestH1BCheckerScrape(unittest.TestCase):
    def test_scrape_year_returns_true_when_rows(self):
        from screening.h1b_checker import H1BChecker
        html_with_rows = (
            "<html><table><tbody><tr><td>STRIPE INC</td></tr></tbody></table></html>"
        )
        session = _mock_session({2025: html_with_rows})
        checker = H1BChecker(_make_db())

        result = asyncio.run(checker._scrape_year(session, "stripe", 2025))
        assert result is True

    def test_scrape_year_returns_false_when_no_data(self):
        from screening.h1b_checker import H1BChecker
        html_no_data = (
            "<html><table><tbody>No data available in table</tbody></table></html>"
        )
        session = _mock_session({2025: html_no_data})
        checker = H1BChecker(_make_db())

        result = asyncio.run(checker._scrape_year(session, "noco", 2025))
        assert result is False

    def test_check_company_returns_true_if_current_year_has_data(self):
        from screening.h1b_checker import H1BChecker
        current_year = datetime.now(timezone.utc).year
        html_rows = "<html><table><tbody><tr><td>X</td></tr></tbody></table></html>"
        html_none = "<html><table><tbody>No data available in table</tbody></table></html>"
        session = _mock_session({current_year: html_rows, current_year - 1: html_none})
        checker = H1BChecker(_make_db())
        sem = asyncio.Semaphore(3)

        result = asyncio.run(checker._check_company(sem, session, "stripe", "Stripe"))
        assert result is True

    def test_check_company_returns_false_if_both_years_empty(self):
        from screening.h1b_checker import H1BChecker
        current_year = datetime.now(timezone.utc).year
        html_none = "<html><table><tbody>No data available in table</tbody></table></html>"
        session = _mock_session({current_year: html_none, current_year - 1: html_none})
        checker = H1BChecker(_make_db())
        sem = asyncio.Semaphore(3)

        result = asyncio.run(checker._check_company(sem, session, "noco", "NoCo"))
        assert result is False

    def test_check_company_returns_none_on_exception(self):
        from screening.h1b_checker import H1BChecker

        async def boom(*args, **kwargs):
            raise aiohttp.ClientError("network failure")

        checker = H1BChecker(_make_db())
        # Patch _scrape_year to raise
        checker._scrape_year = boom
        sem = asyncio.Semaphore(3)
        session = MagicMock()

        result = asyncio.run(checker._check_company(sem, session, "errco", "ErrCo"))
        assert result is None
```

Run: `pytest tests/test_h1b_checker.py::TestH1BCheckerScrape -v`
Expected: FAIL — `AttributeError: 'H1BChecker' has no attribute '_scrape_year'`

- [ ] **Step 2: Add _scrape_year and _check_company to H1BChecker**

Append these methods inside the `H1BChecker` class in `screening/h1b_checker.py`:

```python
    async def _scrape_year(
        self, session: aiohttp.ClientSession, company_key: str, year: int
    ) -> bool:
        url = (
            "https://h1bdata.info/index.php"
            f"?em={urllib.parse.quote_plus(company_key)}&job=&city=&year={year}"
        )
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            html = await resp.text(errors="replace")
        return self._has_results(html)

    async def _check_company(
        self,
        sem: asyncio.Semaphore,
        session: aiohttp.ClientSession,
        company_key: str,
        company_raw: str,
    ) -> bool | None:
        """Return True/False from h1bdata.info, or None on any error."""
        async with sem:
            try:
                year = datetime.now(timezone.utc).year
                results = await asyncio.gather(
                    self._scrape_year(session, company_key, year),
                    self._scrape_year(session, company_key, year - 1),
                    return_exceptions=True,
                )
                if any(r is True for r in results):
                    return True
                if any(isinstance(r, BaseException) for r in results):
                    return None  # at least one request errored — don't penalise
                return False
            except Exception:
                return None
```

Run: `pytest tests/test_h1b_checker.py::TestH1BCheckerScrape -v`
Expected: PASS (5 tests)

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add screening/h1b_checker.py tests/test_h1b_checker.py
git commit -m "feat: add _scrape_year and _check_company to H1BChecker"
```

---

## Task 5: H1BChecker — check_batch (cache + dedup + mutation)

**Files:**
- Modify: `screening/h1b_checker.py`
- Modify: `tests/test_h1b_checker.py`

- [ ] **Step 1: Write failing tests for check_batch**

Add this class to `tests/test_h1b_checker.py`:

```python
class TestH1BCheckerBatch(unittest.TestCase):
    def test_curated_sources_are_skipped(self):
        from screening.h1b_checker import H1BChecker
        checker = H1BChecker(_make_db())
        jobs = [
            _make_job("Anthropic", source="greenhouse-anthropic"),
            _make_job("Scale AI", source="lever-scaleai"),
            _make_job("Weights & Biases", source="ashby-wandb"),
        ]
        asyncio.run(checker.check_batch(jobs))
        for job in jobs:
            assert job.h1b_sponsor_verified is None

    def test_open_source_job_gets_verified_true(self):
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch, AsyncMock

        db = _make_db()
        checker = H1BChecker(db)
        job = _make_job("Stripe", source="linkedin")

        async def fake_check(sem, session, key, raw):
            return True

        with patch.object(checker, "_check_company", side_effect=fake_check):
            asyncio.run(checker.check_batch([job]))

        assert job.h1b_sponsor_verified is True

    def test_open_source_job_gets_verified_false(self):
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch

        db = _make_db()
        checker = H1BChecker(db)
        job = _make_job("TinyStartup", source="remoteok")

        async def fake_check(sem, session, key, raw):
            return False

        with patch.object(checker, "_check_company", side_effect=fake_check):
            asyncio.run(checker.check_batch([job]))

        assert job.h1b_sponsor_verified is False

    def test_error_result_leaves_field_none(self):
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch

        db = _make_db()
        checker = H1BChecker(db)
        job = _make_job("ErrCo", source="hackernews")

        async def fake_check(sem, session, key, raw):
            return None

        with patch.object(checker, "_check_company", side_effect=fake_check):
            asyncio.run(checker.check_batch([job]))

        assert job.h1b_sponsor_verified is None

    def test_cache_hit_skips_scrape(self):
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch

        db = _make_db()
        db.set_h1b_cache("stripe", "Stripe", True)
        checker = H1BChecker(db)
        job = _make_job("Stripe", source="linkedin")

        call_count = 0

        async def fake_check(sem, session, key, raw):
            nonlocal call_count
            call_count += 1
            return False  # should not be called

        with patch.object(checker, "_check_company", side_effect=fake_check):
            asyncio.run(checker.check_batch([job]))

        assert call_count == 0  # served from cache
        assert job.h1b_sponsor_verified is True

    def test_same_company_deduplicated(self):
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch

        db = _make_db()
        checker = H1BChecker(db)
        jobs = [
            _make_job("Stripe", source="linkedin"),
            _make_job("Stripe, Inc.", source="indeed"),
        ]

        call_count = 0

        async def fake_check(sem, session, key, raw):
            nonlocal call_count
            call_count += 1
            return True

        with patch.object(checker, "_check_company", side_effect=fake_check):
            asyncio.run(checker.check_batch(jobs))

        assert call_count == 1  # only one lookup for both Stripe variants
        assert all(j.h1b_sponsor_verified is True for j in jobs)

    def test_verified_result_is_cached(self):
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch

        db = _make_db()
        checker = H1BChecker(db)
        job = _make_job("Datadog", source="linkedin")

        async def fake_check(sem, session, key, raw):
            return False

        with patch.object(checker, "_check_company", side_effect=fake_check):
            asyncio.run(checker.check_batch([job]))

        # The False result must be stored so next run uses cache
        assert db.get_h1b_cache("datadog") is False

    def test_none_result_is_not_cached(self):
        from screening.h1b_checker import H1BChecker
        from unittest.mock import patch

        db = _make_db()
        checker = H1BChecker(db)
        job = _make_job("ErrCo", source="remoteok")

        async def fake_check(sem, session, key, raw):
            return None

        with patch.object(checker, "_check_company", side_effect=fake_check):
            asyncio.run(checker.check_batch([job]))

        assert db.get_h1b_cache("errco") is None  # not stored
```

Run: `pytest tests/test_h1b_checker.py::TestH1BCheckerBatch -v`
Expected: FAIL — `AttributeError: 'H1BChecker' has no attribute 'check_batch'`

- [ ] **Step 2: Add check_batch to H1BChecker**

Append this method inside the `H1BChecker` class in `screening/h1b_checker.py`:

```python
    async def check_batch(self, jobs: list[RawJob]) -> None:
        """Mutate h1b_sponsor_verified on open-source jobs in-place.

        Curated sources (greenhouse-*, lever-*, ashby-*) are left as None.
        Open-source jobs get True/False from cache or h1bdata.info scrape.
        Error results (None) are not cached and leave the field as None.
        """
        open_jobs = [j for j in jobs if not j.source.startswith(_CURATED_PREFIXES)]
        if not open_jobs:
            return

        # Group by normalized company key; keep one raw name per key
        by_key: dict[str, list[RawJob]] = {}
        raw_name: dict[str, str] = {}
        for job in open_jobs:
            key = self._normalize(job.company)
            by_key.setdefault(key, []).append(job)
            raw_name.setdefault(key, job.company)

        # Serve cache hits; collect misses
        verified: dict[str, bool | None] = {}
        misses: list[str] = []
        for key in by_key:
            hit = self._db.get_h1b_cache(key)
            if hit is not None:
                verified[key] = hit
            else:
                misses.append(key)

        # Scrape cache misses concurrently
        if misses:
            sem = asyncio.Semaphore(3)
            async with aiohttp.ClientSession(
                headers={"User-Agent": "Mozilla/5.0"},
            ) as session:
                results = await asyncio.gather(
                    *[
                        self._check_company(sem, session, key, raw_name[key])
                        for key in misses
                    ]
                )
            for key, result in zip(misses, results):
                verified[key] = result
                if result is not None:  # only cache definitive True/False
                    self._db.set_h1b_cache(key, raw_name[key], result)

        # Mutate jobs in-place
        for key, job_list in by_key.items():
            v = verified.get(key)
            for job in job_list:
                job.h1b_sponsor_verified = v
```

Run: `pytest tests/test_h1b_checker.py::TestH1BCheckerBatch -v`
Expected: PASS (8 tests)

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add screening/h1b_checker.py tests/test_h1b_checker.py
git commit -m "feat: add check_batch to H1BChecker with cache, dedup, and in-place mutation"
```

---

## Task 6: Stage 2 prompt + screener changes

**Files:**
- Modify: `prompts/screening.md`
- Modify: `screening/stage2.py`

- [ ] **Step 1: Update prompts/screening.md**

The current `prompts/screening.md` has this JSON template block (lines 16–27). Add `h1b_sponsor_verified` to it:

Replace:
```json
{
  "fingerprint": "company||title (lowercase)",
  "verdict": "APPLY" | "SKIP" | "MAYBE",
  "confidence": 1-5,
  "reasoning": "One sentence explanation",
  "match_signals": ["skill1", "skill2"],
  "risk_flags": ["potential concern"],
  "suggested_angle": "Which resume framing works best"
}
```

With (no change — this is the OUTPUT template; the INPUT JSON is what gets the new field — see step below).

The input JSON for each job is built in `stage2.py`, not in the prompt template itself. But the prompt needs to describe the new field so Claude knows it exists. Add this line after line 36 (`Auto-SKIP: ...`):

Replace:
```
Auto-SKIP: explicit no-sponsorship, security clearance required, 5+ years required, senior/staff level.
```

With:
```
Auto-SKIP: explicit no-sponsorship, security clearance required, 5+ years required, senior/staff level.
If h1b_sponsor_verified is false: add "no_h1b_history" to risk_flags and reduce confidence by 1 (minimum 1). Do not auto-SKIP on this signal alone.
```

- [ ] **Step 2: Update _screen_one_batch in stage2.py to include the field**

In `screening/stage2.py`, find the `jobs_data.append({...})` block inside `_screen_one_batch` (around lines 104–113). Replace it with:

```python
            jobs_data.append({
                "fingerprint": job.fingerprint,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "description": desc,
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "source": job.source,
                "h1b_sponsor_verified": job.h1b_sponsor_verified,
            })
```

- [ ] **Step 3: Update _default_apply and _default_maybe to inject the risk flag**

In `screening/stage2.py`, replace `_default_apply`:

```python
    def _default_apply(self, job: RawJob) -> ScreenedJob:
        risk_flags = ["no_h1b_history"] if job.h1b_sponsor_verified is False else []
        return ScreenedJob(
            **job.model_dump(),
            verdict=ScreeningVerdict.APPLY,
            confidence=2,
            reasoning="Claude screening failed — defaulting to APPLY for manual review",
            suggested_angle="",
            risk_flags=risk_flags,
        )
```

Replace `_default_maybe`:

```python
    def _default_maybe(self, job: RawJob) -> ScreenedJob:
        risk_flags = ["no_h1b_history"] if job.h1b_sponsor_verified is False else []
        return ScreenedJob(
            **job.model_dump(),
            verdict=ScreeningVerdict.MAYBE,
            confidence=2,
            reasoning="Not returned in Claude screening batch — flagged for review",
            suggested_angle="",
            risk_flags=risk_flags,
        )
```

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS. (No new tests needed here — the existing Stage 2 tests exercise the batch path; the fallback paths are covered by the field defaulting to None on existing test jobs, which means `risk_flags=[]`.)

- [ ] **Step 5: Commit**

```bash
git add prompts/screening.md screening/stage2.py
git commit -m "feat: pass h1b_sponsor_verified to Stage 2 prompt and inject no_h1b_history risk flag in fallback paths"
```

---

## Task 7: Wire Phase 7 into main.py

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add H1BChecker import at the top of main.py**

In `main.py`, find the existing import block for screening modules (around line 34):

```python
from screening.stage1 import Stage1Filter
from screening.stage2 import Stage2Screen
```

Add after those two lines:

```python
from screening.h1b_checker import H1BChecker
```

- [ ] **Step 2: Bump TOTAL_PHASES from 9 to 10**

Replace:
```python
TOTAL_PHASES = 9
```

With:
```python
TOTAL_PHASES = 10
```

- [ ] **Step 3: Renumber phases 7, 8, 9 → 8, 9, 10 in run_pipeline()**

There are three `ui.phase(N, ...)` calls that need renumbering. Apply these replacements:

Replace:
```python
    # ── Phase 7: Persist to SQLite ────────────────────────────
    ui.phase(7, "Persisting to SQLite")
```
With:
```python
    # ── Phase 8: Persist to SQLite ────────────────────────────
    ui.phase(8, "Persisting to SQLite")
```

Replace:
```python
    # ── Phase 8: Stage 2 Claude screen ────────────────────────
    ui.phase(8, "Stage 2 Claude CLI precision screen")
```
With:
```python
    # ── Phase 9: Stage 2 Claude screen ────────────────────────
    ui.phase(9, "Stage 2 Claude CLI precision screen")
```

Replace:
```python
    # ── Phase 9: Write Daily + Audit tabs ─────────────���───────
    ui.phase(9, "Writing Daily + Audit tabs")
```
With:
```python
    # ── Phase 10: Write Daily + Audit tabs ────────────────────
    ui.phase(10, "Writing Daily + Audit tabs")
```

- [ ] **Step 4: Insert Phase 7 block between Stage 1 and SQLite persist**

In `run_pipeline()`, find this comment line:

```python
    # ── Phase 7: Persist to SQLite ────────────────────────────
```

(which is now `Phase 8` after the renaming above). Insert the following block **immediately before** it:

```python
    # ── Phase 7: H1B Sponsor Check ───────────────────────────
    ui.phase(7, "H1B Sponsor Check")
    checker = H1BChecker(db)
    await checker.check_batch(passed_jobs)
    n_curated = sum(
        1 for j in passed_jobs if j.source.startswith(("greenhouse-", "lever-", "ashby-"))
    )
    n_verified = sum(1 for j in passed_jobs if j.h1b_sponsor_verified is True)
    n_unverified = sum(1 for j in passed_jobs if j.h1b_sponsor_verified is False)
    ui.phase_done(
        f"{n_verified} verified  ·  {n_unverified} unverified  ·  {n_curated} skipped (curated)"
    )

```

- [ ] **Step 5: Run the full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 6: Smoke-check the pipeline compiles cleanly**

Run: `python -m py_compile main.py screening/h1b_checker.py`
Expected: No output (clean compile).

- [ ] **Step 7: Commit**

```bash
git add main.py
git commit -m "feat: wire H1B sponsor check as Phase 7 in run_pipeline"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Phase 7 between Stage 1 and SQLite persist — Task 7
- [x] Exempt Greenhouse/Lever/Ashby only; Workday checked — `_CURATED_PREFIXES` in Task 3/5
- [x] `h1b_sponsor_verified` field on `RawJob` — Task 1
- [x] `h1b_sponsor_cache` table with TTL — Task 2
- [x] Company name normalization — Task 3
- [x] h1bdata.info scraping (current + previous year) — Task 4
- [x] Semaphore of 3, 10s timeout — Task 4 `_check_company` / `_scrape_year`
- [x] Cache miss → scrape → store (True/False only, not None) — Task 5
- [x] Stage 2 prompt gets `h1b_sponsor_verified` field + guidance line — Task 6
- [x] `_default_apply`/`_default_maybe` inject risk flag from field — Task 6
- [x] Graceful degradation — error → None, no flag — Task 4
- [x] Phase done log line with verified/unverified/curated counts — Task 7

**Type consistency:**
- `H1BChecker._normalize(str) -> str` — used in Task 3 tests and Task 5 `check_batch`
- `H1BChecker._has_results(str) -> bool` — used in Task 3 tests and Task 4 `_scrape_year`
- `H1BChecker._scrape_year(session, key, year) -> bool` — used in Task 4 tests and `_check_company`
- `H1BChecker._check_company(sem, session, key, raw) -> bool | None` — used in Task 4 tests and Task 5 `check_batch`
- `H1BChecker.check_batch(jobs) -> None` — used in Task 5 tests and Task 7 `main.py`
- `Database.get_h1b_cache(key) -> bool | None` — used in Task 2 tests and Task 5 `check_batch`
- `Database.set_h1b_cache(key, raw, verified: bool) -> None` — used in Task 2 tests and Task 5
- `RawJob.h1b_sponsor_verified: bool | None = None` — defined Task 1, used everywhere

All consistent. ✓
