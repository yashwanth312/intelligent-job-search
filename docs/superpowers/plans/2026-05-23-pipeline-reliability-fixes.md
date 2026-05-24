# Pipeline Reliability Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 7 reliability issues found during the 2026-05-23 live monitoring session — silent Stage 2 drops, missing Sheets retry, H1B hang risk, Workday Daily duplication, missing config validation, stale Coinbase token, and invisible source failures.

**Architecture:** Surgical fixes in-place across 8 files. Two helper functions extracted from `main.py` for testability (`_h1b_check_with_timeout`, `_dedup_daily_jobs`). One new file `sheets/_retry.py` for the shared retry helper used by both `daily.py` and `audit.py`.

**Tech Stack:** Python 3.11, asyncio, gspread, pytest, unittest.mock

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `target_companies.yaml` | Modify | Remove stale Coinbase entry |
| `config.py` | Modify | Add `validate_required_config()` |
| `main.py` | Modify | Call config validation; extract `_h1b_check_with_timeout` and `_dedup_daily_jobs`; add Phase 3 error note |
| `screening/stage2.py` | Modify | Log warning when batch returns fewer jobs than submitted |
| `sheets/_retry.py` | Create | `append_rows_with_retry()` helper |
| `sheets/daily.py` | Modify | Use `append_rows_with_retry` |
| `sheets/audit.py` | Modify | Use `append_rows_with_retry` |
| `tests/test_config.py` | Modify | Add config validation tests |
| `tests/test_stage2.py` | Modify | Add batch drop warning test |
| `tests/test_sheets_retry.py` | Create | Tests for retry helper |
| `tests/test_main_helpers.py` | Create | Tests for `_h1b_check_with_timeout` and `_dedup_daily_jobs` |
| `tests/test_orchestrator.py` | Modify | Add test that error messages include adapter name |

---

## Task 1: Remove Stale Coinbase Token

**Files:**
- Modify: `target_companies.yaml`

No test needed — Coinbase is returning HTTP 404 (zero jobs). Removing it is a data change with no behavioral impact.

- [ ] **Step 1: Find and remove the Coinbase entry**

Open `target_companies.yaml`, find the line `- coinbase` under the `greenhouse:` key and delete it.

- [ ] **Step 2: Verify the file is valid YAML**

```bash
python -c "import yaml; yaml.safe_load(open('target_companies.yaml'))"
```

Expected: exits with no output (no error).

- [ ] **Step 3: Commit**

```bash
git add target_companies.yaml
git commit -m "fix: remove stale Coinbase Greenhouse token (HTTP 404 every run)"
```

---

## Task 2: Config Validation at Startup

**Files:**
- Modify: `config.py`
- Modify: `main.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add to the bottom of `tests/test_config.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import patch


class TestValidateRequiredConfig:
    def test_passes_when_all_set(self, tmp_path):
        creds = tmp_path / "credentials.json"
        creds.touch()
        with patch("config.YOUR_NAME", "Test User"), \
             patch("config.YOUR_EMAIL", "test@example.com"), \
             patch("config.GOOGLE_SHEETS_CREDS_FILE", str(creds)):
            from config import validate_required_config
            validate_required_config()  # must not raise

    def test_fails_missing_name(self, tmp_path):
        creds = tmp_path / "credentials.json"
        creds.touch()
        with patch("config.YOUR_NAME", ""), \
             patch("config.YOUR_EMAIL", "test@example.com"), \
             patch("config.GOOGLE_SHEETS_CREDS_FILE", str(creds)):
            from config import validate_required_config
            with pytest.raises(SystemExit) as exc:
                validate_required_config()
            assert "YOUR_NAME" in str(exc.value)

    def test_fails_missing_email(self, tmp_path):
        creds = tmp_path / "credentials.json"
        creds.touch()
        with patch("config.YOUR_NAME", "Test User"), \
             patch("config.YOUR_EMAIL", ""), \
             patch("config.GOOGLE_SHEETS_CREDS_FILE", str(creds)):
            from config import validate_required_config
            with pytest.raises(SystemExit) as exc:
                validate_required_config()
            assert "YOUR_EMAIL" in str(exc.value)

    def test_fails_missing_creds_file(self, tmp_path):
        with patch("config.YOUR_NAME", "Test User"), \
             patch("config.YOUR_EMAIL", "test@example.com"), \
             patch("config.GOOGLE_SHEETS_CREDS_FILE", str(tmp_path / "nope.json")):
            from config import validate_required_config
            with pytest.raises(SystemExit) as exc:
                validate_required_config()
            assert "GOOGLE_SHEETS_CREDS_FILE" in str(exc.value)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py::TestValidateRequiredConfig -v
```

Expected: `ImportError` or `AttributeError: module 'config' has no attribute 'validate_required_config'`

- [ ] **Step 3: Add `validate_required_config` to `config.py`**

Add at the bottom of `config.py` (after all the variable definitions, before the end of the file):

```python
# ── STARTUP VALIDATION ────────────────────────────────────
def validate_required_config() -> None:
    """Raise SystemExit with a clear message if required config is missing."""
    from pathlib import Path
    missing = []
    if not YOUR_NAME:
        missing.append("YOUR_NAME (set in .env)")
    if not YOUR_EMAIL:
        missing.append("YOUR_EMAIL (set in .env)")
    if not Path(GOOGLE_SHEETS_CREDS_FILE).exists():
        missing.append(f"GOOGLE_SHEETS_CREDS_FILE={GOOGLE_SHEETS_CREDS_FILE!r} (file not found)")
    if missing:
        raise SystemExit(
            "Missing required config:\n" + "\n".join(f"  • {m}" for m in missing)
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py::TestValidateRequiredConfig -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Call `validate_required_config()` in Phase 1 of `main.py`**

In `main.py`, find Phase 1 (starts around line 119):

```python
    # ── Phase 1: Init ─────────────────────────────────────────
    ui.phase(1, "Initializing (profile, DB, Google creds)")
    if not Path("profile.yaml").exists():
```

Add the validation call right after `ui.phase(1, ...)`:

```python
    # ── Phase 1: Init ─────────────────────────────────────────
    ui.phase(1, "Initializing (profile, DB, Google creds)")
    from config import validate_required_config
    validate_required_config()
    if not Path("profile.yaml").exists():
```

- [ ] **Step 6: Run full config test suite to confirm no regressions**

```bash
pytest tests/test_config.py -v
```

Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add config.py main.py tests/test_config.py
git commit -m "feat: validate required config at pipeline startup (Phase 1)"
```

---

## Task 3: Stage 2 Silent Batch Drop Warning

**Files:**
- Modify: `screening/stage2.py`
- Modify: `tests/test_stage2.py`

- [ ] **Step 1: Write the failing test**

Add to the bottom of `tests/test_stage2.py`:

```python
def test_screen_batch_warns_on_partial_response():
    """When Claude returns fewer jobs than submitted, a WARNING is logged naming the missing jobs."""
    from unittest.mock import patch
    from models.job import RawJob

    jobs = [
        RawJob(title="Cloud Engineer", company="Acme", location="Remote",
               url="https://a.com", source="linkedin"),
        RawJob(title="DevOps Engineer", company="Beta", location="Remote",
               url="https://b.com", source="linkedin"),
    ]
    # Only the first job is returned by Claude
    partial = [{
        "fingerprint": jobs[0].fingerprint,
        "verdict": "APPLY", "confidence": 4, "reasoning": "Good",
        "match_signals": [], "risk_flags": [], "suggested_angle": "",
    }]

    screen = Stage2Screen(profile_path="profile.yaml")
    with patch.object(screen, "_screen_one_batch", return_value=partial), \
         patch.object(screen, "_load_profile_summary", return_value="summary"), \
         patch("screening.stage2.logger") as mock_log:
        result = screen.screen_batch(jobs)

    mock_log.warning.assert_called_once()
    msg = mock_log.warning.call_args[0][0]
    assert "1/2 returned" in msg
    assert "DevOps Engineer" in msg
    assert len(result) == 2  # both jobs still in output (one APPLY, one MAYBE)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_stage2.py::test_screen_batch_warns_on_partial_response -v
```

Expected: FAIL — `AssertionError: assert 0 == 1` (warning was never called)

- [ ] **Step 3: Add the warning to `screening/stage2.py`**

In `stage2.py`, find `screen_batch`. After the line `result_map = {r["fingerprint"]: r for r in batch_results}`, add:

```python
            result_map = {r["fingerprint"]: r for r in batch_results}
            missing = [j for j in batch if j.fingerprint not in result_map]
            if missing:
                titles = ", ".join(j.title for j in missing)
                logger.warning(
                    f"Stage 2 batch {i // SCREENING_BATCH_SIZE + 1}: "
                    f"{len(result_map)}/{len(batch)} returned — "
                    f"defaulting to MAYBE for: {titles}"
                )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_stage2.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add screening/stage2.py tests/test_stage2.py
git commit -m "feat: log warning when Stage 2 batch returns fewer jobs than submitted"
```

---

## Task 4: Google Sheets Write Retry Helper

**Files:**
- Create: `sheets/_retry.py`
- Modify: `sheets/daily.py`
- Modify: `sheets/audit.py`
- Create: `tests/test_sheets_retry.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sheets_retry.py`:

```python
"""Tests for the Sheets write retry helper."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


def test_succeeds_on_first_attempt():
    from sheets._retry import append_rows_with_retry
    ws = MagicMock()
    rows = [["a", "b"], ["c", "d"]]
    append_rows_with_retry(ws, rows)
    ws.append_rows.assert_called_once_with(rows, value_input_option="USER_ENTERED")


def test_retries_on_failure_then_succeeds():
    from sheets._retry import append_rows_with_retry
    ws = MagicMock()
    ws.append_rows.side_effect = [Exception("quota exceeded"), Exception("timeout"), None]
    with patch("sheets._retry.time.sleep"):
        append_rows_with_retry(ws, [["a"]], max_attempts=3)
    assert ws.append_rows.call_count == 3


def test_raises_after_max_attempts_exhausted():
    from sheets._retry import append_rows_with_retry
    ws = MagicMock()
    ws.append_rows.side_effect = Exception("permanent error")
    with patch("sheets._retry.time.sleep"), \
         pytest.raises(Exception, match="permanent error"):
        append_rows_with_retry(ws, [["a"]], max_attempts=3)
    assert ws.append_rows.call_count == 3


def test_logs_sqlite_message_after_max_attempts():
    from sheets._retry import append_rows_with_retry
    ws = MagicMock()
    ws.append_rows.side_effect = Exception("error")
    with patch("sheets._retry.time.sleep"), \
         patch("sheets._retry.logger") as mock_log, \
         pytest.raises(Exception):
        append_rows_with_retry(ws, [["a"]], max_attempts=2)
    mock_log.error.assert_called_once()
    assert "SQLite" in mock_log.error.call_args[0][0]


def test_passes_value_input_option():
    from sheets._retry import append_rows_with_retry
    ws = MagicMock()
    append_rows_with_retry(ws, [["a"]], value_input_option="RAW")
    ws.append_rows.assert_called_once_with([["a"]], value_input_option="RAW")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_sheets_retry.py -v
```

Expected: `ModuleNotFoundError: No module named 'sheets._retry'`

- [ ] **Step 3: Create `sheets/_retry.py`**

```python
"""Retry helper for gspread append_rows calls."""
from __future__ import annotations

import logging
import time

import gspread

logger = logging.getLogger(__name__)


def append_rows_with_retry(
    ws: gspread.Worksheet,
    rows: list[list],
    value_input_option: str = "USER_ENTERED",
    max_attempts: int = 3,
    backoff_base: float = 2.0,
) -> None:
    """Call ws.append_rows with exponential backoff retry.

    On final failure, logs a clear error that results are safely in SQLite,
    then re-raises so the caller is aware.
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            ws.append_rows(rows, value_input_option=value_input_option)
            return
        except Exception as e:
            last_exc = e
            if attempt < max_attempts - 1:
                wait = backoff_base ** attempt
                logger.warning(
                    f"Sheets write attempt {attempt + 1}/{max_attempts} failed: {e}"
                    f" — retrying in {wait:.0f}s"
                )
                time.sleep(wait)
    logger.error(
        f"Google Sheets write failed after {max_attempts} attempts — "
        "results are in SQLite but not visible in Sheets"
    )
    raise last_exc
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_sheets_retry.py -v
```

Expected: 5 tests PASS

- [ ] **Step 5: Update `sheets/daily.py` to use the retry helper**

In `sheets/daily.py`, replace the `ws.append_rows(...)` call at the bottom of `write_screened_jobs`:

Before:
```python
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info(f"Daily tab: wrote {len(rows)} jobs (sorted by confidence desc)")
```

After:
```python
    if rows:
        from sheets._retry import append_rows_with_retry
        append_rows_with_retry(ws, rows, value_input_option="USER_ENTERED")
        logger.info(f"Daily tab: wrote {len(rows)} jobs (sorted by confidence desc)")
```

- [ ] **Step 6: Update `sheets/audit.py` to use the retry helper**

In `sheets/audit.py`, replace the `ws.append_rows(...)` call in `write_rejections`:

Before:
```python
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info(f"Audit tab: wrote {len(rows)} rejections")
```

After:
```python
    if rows:
        from sheets._retry import append_rows_with_retry
        append_rows_with_retry(ws, rows, value_input_option="USER_ENTERED")
        logger.info(f"Audit tab: wrote {len(rows)} rejections")
```

- [ ] **Step 7: Run all sheets-related tests**

```bash
pytest tests/test_sheets_retry.py tests/test_daily_columns.py tests/test_daily_sponsorship.py -v
```

Expected: all tests PASS

- [ ] **Step 8: Commit**

```bash
git add sheets/_retry.py sheets/daily.py sheets/audit.py tests/test_sheets_retry.py
git commit -m "feat: add exponential backoff retry to Google Sheets writes"
```

---

## Task 5: H1B Checker Wall-Clock Timeout

**Files:**
- Modify: `main.py`
- Create: `tests/test_main_helpers.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_main_helpers.py`:

```python
"""Tests for helper functions extracted from main.py."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


async def _never_returns(*args, **kwargs):
    """Coroutine that never completes — simulates a hung H1B checker."""
    await asyncio.sleep(9999)


@pytest.mark.asyncio
async def test_h1b_timeout_continues_without_raising():
    """When H1B checker hangs, the helper catches TimeoutError and returns normally."""
    from main import _h1b_check_with_timeout
    checker = MagicMock()
    checker.check_batch = _never_returns
    # timeout=0.01s ensures it fires immediately; must not raise
    await _h1b_check_with_timeout(checker, [], timeout=0.01)


@pytest.mark.asyncio
async def test_h1b_timeout_calls_checker_normally_when_fast():
    """When H1B checker completes quickly, it is called exactly once."""
    from main import _h1b_check_with_timeout
    checker = MagicMock()
    checker.check_batch = AsyncMock()
    await _h1b_check_with_timeout(checker, [], timeout=5)
    checker.check_batch.assert_called_once_with([])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_main_helpers.py -v
```

Expected: `ImportError: cannot import name '_h1b_check_with_timeout' from 'main'`

- [ ] **Step 3: Add `_h1b_check_with_timeout` to `main.py`**

Add this function just before `run_pipeline()` in `main.py` (around line 115):

```python
async def _h1b_check_with_timeout(checker: "H1BChecker", jobs: list, timeout: int = 300) -> None:
    """Run H1B check with a wall-clock timeout. On timeout, log and continue with None status."""
    try:
        await asyncio.wait_for(checker.check_batch(jobs), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(
            f"H1B checker timed out after {timeout}s — "
            "all jobs proceeding with h1b_sponsor_verified=None"
        )
```

- [ ] **Step 4: Replace the bare `await checker.check_batch(...)` call in Phase 5**

Find in `main.py` Phase 5 (around line 182):

```python
    checker = H1BChecker(db)
    await checker.check_batch(unique_jobs)
```

Replace with:

```python
    checker = H1BChecker(db)
    await _h1b_check_with_timeout(checker, unique_jobs)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_main_helpers.py -v
```

Expected: 2 tests PASS

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main_helpers.py
git commit -m "feat: add wall-clock timeout to H1B checker (300s) to prevent pipeline hangs"
```

---

## Task 6: Workday Dedup Before Daily Write

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main_helpers.py`

- [ ] **Step 1: Add tests to `tests/test_main_helpers.py`**

Append to the existing `tests/test_main_helpers.py`:

```python
def _make_screened(title, company, confidence, verdict_str, reasoning="", risk_flags=None):
    from models.job import ScreenedJob, ScreeningVerdict
    return ScreenedJob(
        title=title, company=company, location="Remote",
        url=f"https://example.com/{company.lower()}",
        source="greenhouse-test",
        verdict=ScreeningVerdict(verdict_str),
        confidence=confidence,
        reasoning=reasoning,
        match_signals=[],
        risk_flags=risk_flags or [],
    )


def test_dedup_daily_jobs_removes_lower_confidence_duplicate():
    from main import _dedup_daily_jobs
    screened = _make_screened("Cloud Engineer", "Acme", confidence=4, verdict_str="APPLY")
    unscreened = _make_screened("Cloud Engineer", "Acme", confidence=1, verdict_str="MAYBE",
                                reasoning="No JD available", risk_flags=["no_description"])
    result = _dedup_daily_jobs([unscreened, screened])
    assert len(result) == 1
    assert result[0].confidence == 4


def test_dedup_daily_jobs_passthrough_unique_jobs():
    from main import _dedup_daily_jobs
    job_a = _make_screened("Cloud Engineer", "Acme", confidence=4, verdict_str="APPLY")
    job_b = _make_screened("DevOps Engineer", "Beta", confidence=3, verdict_str="MAYBE")
    result = _dedup_daily_jobs([job_a, job_b])
    assert len(result) == 2


def test_dedup_daily_jobs_empty_list():
    from main import _dedup_daily_jobs
    assert _dedup_daily_jobs([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_main_helpers.py::test_dedup_daily_jobs_removes_lower_confidence_duplicate -v
```

Expected: `ImportError: cannot import name '_dedup_daily_jobs' from 'main'`

- [ ] **Step 3: Add `_dedup_daily_jobs` to `main.py`**

Add this function directly below `_h1b_check_with_timeout` in `main.py`:

```python
def _dedup_daily_jobs(jobs: list["ScreenedJob"]) -> list["ScreenedJob"]:
    """Deduplicate Daily jobs by fingerprint, keeping the highest-confidence version."""
    seen: set[str] = set()
    result: list = []
    for job in sorted(jobs, key=lambda j: j.confidence, reverse=True):
        if job.fingerprint not in seen:
            seen.add(job.fingerprint)
            result.append(job)
        else:
            logger.warning(
                f"Dedup: removed duplicate daily entry for {job.company} — {job.title}"
            )
    return result
```

- [ ] **Step 4: Call `_dedup_daily_jobs` in Phase 9 of `main.py`**

Find the Phase 9 block (around line 370). Just before `daily_ops.write_screened_jobs(daily_ws, daily_jobs)`:

Before:
```python
    daily_ops.write_screened_jobs(daily_ws, daily_jobs)
```

After:
```python
    daily_jobs = _dedup_daily_jobs(daily_jobs)
    daily_ops.write_screened_jobs(daily_ws, daily_jobs)
```

- [ ] **Step 5: Run all main helper tests**

```bash
pytest tests/test_main_helpers.py -v
```

Expected: all 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main_helpers.py
git commit -m "feat: deduplicate daily_jobs by fingerprint before Sheets write"
```

---

## Task 7: Per-Source Failure Count in Phase 3 Summary

**Files:**
- Modify: `main.py`
- Modify: `tests/test_orchestrator.py`

The `ScraperOrchestrator._safe_scrape` already formats errors as `f"{adapter.name}: {e}"` and populates `SourceResult.errors`. No orchestrator changes needed — we only need to surface the error count in the Phase 3 `ui.phase_done()` line.

- [ ] **Step 1: Add test to confirm error messages include the adapter name**

Add to `tests/test_orchestrator.py` inside `class TestOrchestrator`:

```python
    @pytest.mark.asyncio
    async def test_error_message_includes_adapter_name(self):
        bad = FailingSource()  # name = "failing"
        orchestrator = ScraperOrchestrator(adapters=[bad])
        result = await orchestrator.scrape_all(["Job"], ["NYC"])
        assert len(result.errors) == 1
        assert "failing" in result.errors[0]
```

- [ ] **Step 2: Run test to verify it passes (behaviour already exists)**

```bash
pytest tests/test_orchestrator.py::TestOrchestrator::test_error_message_includes_adapter_name -v
```

Expected: PASS — this is a characterisation test confirming existing behaviour we rely on.

- [ ] **Step 3: Update Phase 3 `ui.phase_done()` in `main.py`**

Find in `main.py` Phase 3 (around line 158):

```python
    ui.phase_done(f"{len(all_scraped)} unique jobs after cross-source + DB dedup")
```

Replace with:

```python
    error_note = f"  ·  {len(scrape_result.errors)} source error(s)" if scrape_result.errors else ""
    ui.phase_done(f"{len(all_scraped)} unique jobs after cross-source + DB dedup{error_note}")
```

- [ ] **Step 4: Run orchestrator tests to confirm no regressions**

```bash
pytest tests/test_orchestrator.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_orchestrator.py
git commit -m "feat: show source error count in Phase 3 phase_done summary line"
```

---

## Final Verification

- [ ] **Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all tests PASS, no regressions.

- [ ] **Type-check the modified files**

```bash
python -m py_compile config.py main.py screening/stage2.py sheets/_retry.py sheets/daily.py sheets/audit.py sources/orchestrator.py
```

Expected: exits silently (no syntax errors).
