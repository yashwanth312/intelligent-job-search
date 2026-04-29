# Sponsorship Pipeline Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move H1B sponsor check from Phase 7 to Phase 5 with source-aware drop, add a dedicated `Sponsorship` column to the Daily tab, and reorder `Risk Flags` to appear right after `Status` — cutting pipeline runtime from the ~7.5h baseline while protecting startup-friendly sources from h1bdata.info false negatives.

**Architecture:** A new `partition_drops()` helper in `screening/h1b_checker.py` partitions H1B-checked jobs into `(kept, dropped)` based on source bucket (LinkedIn/Indeed/Google/Workday = drop bucket; HN/RemoteOK/curated ATS = keep bucket). The phase reorder in `main.py` runs the H1B check immediately after the freshness filter so non-sponsors from drop-bucket sources never trigger description backfill or Stage 2 Claude screening. The `no_h1b_history` risk flag is removed — sponsorship state is rendered into a dedicated Daily tab column derived from `RawJob.h1b_sponsor_verified` plus source.

**Tech Stack:** Python 3, pydantic models, gspread, aiohttp (existing). Tests use pytest + unittest mixed style.

**Spec:** [docs/superpowers/specs/2026-04-29-sponsorship-pipeline-redesign.md](../specs/2026-04-29-sponsorship-pipeline-redesign.md)

---

## Task 1: Add `is_droppable_source` and `partition_drops` to h1b_checker

**Files:**
- Test: `tests/test_h1b_partition.py` (create)
- Modify: `screening/h1b_checker.py`

- [ ] **Step 1.1: Write the failing test file**

Create `tests/test_h1b_partition.py`:

```python
"""Tests for source-aware drop partitioning in screening.h1b_checker."""
from __future__ import annotations

from models.job import RawJob
from screening.h1b_checker import is_droppable_source, partition_drops


def _job(source: str, verified: bool | None) -> RawJob:
    return RawJob(
        title="Cloud Engineer",
        company="Acme",
        location="Remote",
        url="https://example.com/job",
        source=source,
        h1b_sponsor_verified=verified,
    )


class TestIsDroppableSource:
    def test_linkedin_is_droppable(self):
        assert is_droppable_source("linkedin") is True

    def test_indeed_is_droppable(self):
        assert is_droppable_source("indeed") is True

    def test_google_is_droppable(self):
        assert is_droppable_source("google") is True

    def test_workday_is_droppable(self):
        assert is_droppable_source("workday") is True

    def test_hackernews_is_not_droppable(self):
        assert is_droppable_source("hackernews") is False

    def test_remoteok_is_not_droppable(self):
        assert is_droppable_source("remoteok") is False

    def test_greenhouse_prefixed_is_not_droppable(self):
        assert is_droppable_source("greenhouse-anthropic") is False

    def test_lever_prefixed_is_not_droppable(self):
        assert is_droppable_source("lever-stripe") is False

    def test_ashby_prefixed_is_not_droppable(self):
        assert is_droppable_source("ashby-foo") is False

    def test_unknown_source_is_not_droppable(self):
        # Conservative default: don't drop sources we don't recognize
        assert is_droppable_source("some-new-source") is False


class TestPartitionDrops:
    def test_verified_false_from_droppable_source_is_dropped(self):
        jobs = [_job("linkedin", False)]
        kept, dropped = partition_drops(jobs)
        assert kept == []
        assert dropped == jobs

    def test_verified_false_from_keep_source_is_kept(self):
        jobs = [
            _job("hackernews", False),
            _job("remoteok", False),
            _job("greenhouse-anthropic", False),
            _job("lever-stripe", False),
            _job("ashby-foo", False),
        ]
        kept, dropped = partition_drops(jobs)
        assert kept == jobs
        assert dropped == []

    def test_verified_true_is_kept_from_any_source(self):
        jobs = [
            _job("linkedin", True),
            _job("indeed", True),
            _job("hackernews", True),
            _job("greenhouse-foo", True),
        ]
        kept, dropped = partition_drops(jobs)
        assert kept == jobs
        assert dropped == []

    def test_verified_none_is_kept_from_any_source(self):
        jobs = [
            _job("linkedin", None),
            _job("indeed", None),
            _job("greenhouse-foo", None),
        ]
        kept, dropped = partition_drops(jobs)
        assert kept == jobs
        assert dropped == []

    def test_mixed_batch(self):
        keep_a = _job("linkedin", True)
        drop_a = _job("indeed", False)
        keep_b = _job("hackernews", False)  # kept despite False because source
        keep_c = _job("greenhouse-x", None)
        drop_b = _job("workday", False)

        kept, dropped = partition_drops([keep_a, drop_a, keep_b, keep_c, drop_b])
        assert kept == [keep_a, keep_b, keep_c]
        assert dropped == [drop_a, drop_b]

    def test_empty_input(self):
        kept, dropped = partition_drops([])
        assert kept == []
        assert dropped == []
```

- [ ] **Step 1.2: Run the test file to verify it fails**

Run: `pytest tests/test_h1b_partition.py -v`
Expected: ImportError — `is_droppable_source` and `partition_drops` not yet defined in `screening.h1b_checker`.

- [ ] **Step 1.3: Add the two helpers to `screening/h1b_checker.py`**

Append to the bottom of `screening/h1b_checker.py` (after the `H1BChecker` class):

```python
# Sources where "no H-1B history" reliably means "won't sponsor".
# These skew toward established companies; if they have zero LCA
# filings on record, dropping them is safe.
_DROPPABLE_SOURCES = frozenset({"linkedin", "indeed", "google", "workday"})


def is_droppable_source(source: str) -> bool:
    """Return True if a source belongs to the big-company drop bucket.

    Sources outside this set are either user-curated (greenhouse/lever/ashby
    prefixes) or startup-heavy (hackernews, remoteok), where a missing
    h1bdata.info record is uninformative.
    """
    return source in _DROPPABLE_SOURCES


def partition_drops(jobs: list[RawJob]) -> tuple[list[RawJob], list[RawJob]]:
    """Split a list of H1B-checked jobs into (kept, dropped).

    A job is dropped iff its source is in the drop bucket AND its
    h1b_sponsor_verified is False (definitively no LCA filings).
    All other combinations — verified=True, verified=None, or any
    keep-bucket source — pass through unchanged.

    Pre-condition: callers should run H1BChecker.check_batch first so
    h1b_sponsor_verified is populated where applicable.
    """
    kept: list[RawJob] = []
    dropped: list[RawJob] = []
    for job in jobs:
        if job.h1b_sponsor_verified is False and is_droppable_source(job.source):
            dropped.append(job)
        else:
            kept.append(job)
    return kept, dropped
```

- [ ] **Step 1.4: Run the test file to verify it passes**

Run: `pytest tests/test_h1b_partition.py -v`
Expected: All 18 tests PASS.

- [ ] **Step 1.5: Commit**

```bash
git add tests/test_h1b_partition.py screening/h1b_checker.py
git commit -m "feat: add source-aware drop partitioning to H1B checker"
```

---

## Task 2: Add `_sponsorship_label` helper to `sheets/daily.py`

**Files:**
- Test: `tests/test_daily_sponsorship.py` (create)
- Modify: `sheets/daily.py`

- [ ] **Step 2.1: Write the failing test**

Create `tests/test_daily_sponsorship.py`:

```python
"""Tests for the Sponsorship column label derivation."""
from __future__ import annotations

from models.job import ScreenedJob, ScreeningVerdict
from sheets.daily import _sponsorship_label


def _screened(source: str, verified: bool | None) -> ScreenedJob:
    return ScreenedJob(
        title="Cloud Engineer",
        company="Acme",
        location="Remote",
        url="https://example.com/job",
        source=source,
        h1b_sponsor_verified=verified,
        verdict=ScreeningVerdict.APPLY,
        confidence=4,
        reasoning="ok",
    )


def test_verified_true_returns_verified_sponsor():
    job = _screened("linkedin", True)
    assert _sponsorship_label(job) == "Verified sponsor"


def test_verified_false_returns_no_history():
    # Only kept jobs (HN/RemoteOK/curated) reach this with False
    job = _screened("hackernews", False)
    assert _sponsorship_label(job) == "No H-1B history"


def test_curated_source_with_none_returns_curated_unknown():
    for source in ("greenhouse-anthropic", "lever-stripe", "ashby-foo"):
        job = _screened(source, None)
        assert _sponsorship_label(job) == "Curated — unknown"


def test_non_curated_source_with_none_returns_blank():
    job = _screened("hackernews", None)
    assert _sponsorship_label(job) == ""


def test_non_curated_unknown_source_with_none_returns_blank():
    job = _screened("remoteok", None)
    assert _sponsorship_label(job) == ""
```

- [ ] **Step 2.2: Run the test to verify it fails**

Run: `pytest tests/test_daily_sponsorship.py -v`
Expected: ImportError — `_sponsorship_label` not yet defined in `sheets.daily`.

- [ ] **Step 2.3: Add the helper to `sheets/daily.py`**

In `sheets/daily.py`, add this function above `clear_and_write_headers` (i.e. after `_humanize_posted`):

```python
def _sponsorship_label(job: ScreenedJob) -> str:
    """Render the Sponsorship column for a screened job.

    True  → "Verified sponsor" (LCA filings found on h1bdata.info)
    False → "No H-1B history" (only reaches Daily for kept-bucket sources)
    None  + curated ATS source → "Curated — unknown"
    None  + other source → "" (blank)
    """
    if job.h1b_sponsor_verified is True:
        return "Verified sponsor"
    if job.h1b_sponsor_verified is False:
        return "No H-1B history"
    if job.source.startswith(("greenhouse-", "lever-", "ashby-")):
        return "Curated — unknown"
    return ""
```

- [ ] **Step 2.4: Run the test to verify it passes**

Run: `pytest tests/test_daily_sponsorship.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 2.5: Commit**

```bash
git add tests/test_daily_sponsorship.py sheets/daily.py
git commit -m "feat: add sponsorship column label helper"
```

---

## Task 3: Update `DAILY_HEADERS` and add column-order test

**Files:**
- Test: `tests/test_daily_columns.py` (create)
- Modify: `config.py`

- [ ] **Step 3.1: Write the failing test**

Create `tests/test_daily_columns.py`:

```python
"""Tests for Daily tab column count, order, and key positions."""
from __future__ import annotations

from config import DAILY_HEADERS


EXPECTED_HEADERS = [
    "Company",          # 0
    "Job Title",        # 1
    "Location",         # 2
    "Confidence",       # 3
    "Status",           # 4
    "Risk Flags",       # 5  ← moved up from col 11
    "Apply Link",       # 6
    "Posted",           # 7
    "Source",           # 8
    "AI Reasoning",     # 9
    "Suggested Angle",  # 10
    "Match Signals",    # 11
    "Sponsorship",      # 12 ← new
    "Salary Range",     # 13
    "Notes",            # 14
]


def test_daily_headers_exact_match():
    assert DAILY_HEADERS == EXPECTED_HEADERS


def test_daily_headers_count_is_15():
    assert len(DAILY_HEADERS) == 15


def test_status_is_at_index_4():
    assert DAILY_HEADERS[4] == "Status"


def test_risk_flags_immediately_follows_status():
    assert DAILY_HEADERS[5] == "Risk Flags"


def test_sponsorship_is_at_index_12():
    assert DAILY_HEADERS[12] == "Sponsorship"
```

- [ ] **Step 3.2: Run the test to verify it fails**

Run: `pytest tests/test_daily_columns.py -v`
Expected: 5 FAIL — current headers are 14 entries with Risk Flags at col 11 and no Sponsorship column.

- [ ] **Step 3.3: Update `DAILY_HEADERS` in `config.py`**

In `config.py`, replace the `DAILY_HEADERS` block (lines 192-199) with:

```python
# ── DAILY TAB COLUMNS ─────────────────────────────────────
# Risk Flags sits right after Status so visa/clearance/seniority
# concerns are visible without scrolling. Sponsorship is a dedicated
# column derived from h1b_sponsor_verified + source — replaces the old
# `no_h1b_history` risk flag.
DAILY_HEADERS = [
    "Company", "Job Title", "Location", "Confidence", "Status", "Risk Flags",
    "Apply Link", "Posted", "Source", "AI Reasoning", "Suggested Angle",
    "Match Signals", "Sponsorship", "Salary Range", "Notes",
]
```

- [ ] **Step 3.4: Run the test to verify it passes**

Run: `pytest tests/test_daily_columns.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 3.5: Commit**

```bash
git add tests/test_daily_columns.py config.py
git commit -m "feat: reorder DAILY_HEADERS — Risk Flags after Status, add Sponsorship"
```

---

## Task 4: Wire `daily.py` row builder to new column order

**Files:**
- Modify: `sheets/daily.py:40-71` (the `write_screened_jobs` function)
- Test: extend `tests/test_daily_sponsorship.py` with row-shape assertions

- [ ] **Step 4.1: Append row-shape tests to `tests/test_daily_sponsorship.py`**

Append to the bottom of `tests/test_daily_sponsorship.py`:

```python
from unittest.mock import MagicMock

from sheets.daily import write_screened_jobs


def _ws_mock():
    """Minimal worksheet stand-in capturing append_rows calls."""
    ws = MagicMock()
    return ws


def test_write_screened_jobs_emits_15_columns_per_row():
    ws = _ws_mock()
    jobs = [_screened("linkedin", True), _screened("hackernews", False)]
    write_screened_jobs(ws, jobs)

    assert ws.append_rows.called
    rows = ws.append_rows.call_args[0][0]
    assert len(rows) == 2
    for row in rows:
        assert len(row) == 15, f"row has {len(row)} cells, expected 15"


def test_write_screened_jobs_status_at_index_4_blank():
    ws = _ws_mock()
    write_screened_jobs(ws, [_screened("linkedin", True)])
    row = ws.append_rows.call_args[0][0][0]
    # Status is user-filled; the row builder writes ""
    assert row[4] == ""


def test_write_screened_jobs_risk_flags_at_index_5():
    ws = _ws_mock()
    job = _screened("linkedin", True)
    job.risk_flags = ["seniority_mismatch", "salary_below_floor"]
    write_screened_jobs(ws, [job])
    row = ws.append_rows.call_args[0][0][0]
    assert row[5] == "seniority_mismatch, salary_below_floor"


def test_write_screened_jobs_sponsorship_at_index_12():
    ws = _ws_mock()
    write_screened_jobs(ws, [_screened("linkedin", True)])
    row = ws.append_rows.call_args[0][0][0]
    assert row[12] == "Verified sponsor"


def test_write_screened_jobs_sponsorship_no_history():
    ws = _ws_mock()
    write_screened_jobs(ws, [_screened("hackernews", False)])
    row = ws.append_rows.call_args[0][0][0]
    assert row[12] == "No H-1B history"


def test_write_screened_jobs_sponsorship_curated_unknown():
    ws = _ws_mock()
    write_screened_jobs(ws, [_screened("greenhouse-anthropic", None)])
    row = ws.append_rows.call_args[0][0][0]
    assert row[12] == "Curated — unknown"
```

- [ ] **Step 4.2: Run the new tests to verify they fail**

Run: `pytest tests/test_daily_sponsorship.py -v`
Expected: The 6 new tests FAIL — current row builder writes 14 cells in the old order.

- [ ] **Step 4.3: Update `write_screened_jobs` in `sheets/daily.py`**

Replace the body of `write_screened_jobs` (lines 40-71) with:

```python
def write_screened_jobs(ws: gspread.Worksheet, jobs: list[ScreenedJob]) -> None:
    # Sort by confidence descending so best matches are at the top
    sorted_jobs = sorted(jobs, key=lambda j: j.confidence, reverse=True)

    rows = []
    for job in sorted_jobs:
        salary = ""
        if job.salary_min and job.salary_max:
            salary = f"${job.salary_min:,} - ${job.salary_max:,}"
        elif job.salary_min:
            salary = f"${job.salary_min:,}+"

        rows.append([
            job.company,                          # 0  Company
            job.title,                            # 1  Job Title
            job.location,                         # 2  Location
            job.confidence,                       # 3  Confidence
            "",                                   # 4  Status (user fills)
            ", ".join(job.risk_flags),            # 5  Risk Flags
            job.url,                              # 6  Apply Link
            _humanize_posted(job.posted_at),      # 7  Posted (e.g. "3h ago")
            job.source,                           # 8  Source
            job.reasoning,                        # 9  AI Reasoning
            job.suggested_angle,                  # 10 Suggested Angle
            ", ".join(job.match_signals),         # 11 Match Signals
            _sponsorship_label(job),              # 12 Sponsorship
            salary,                               # 13 Salary Range
            "",                                   # 14 Notes
        ])

    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info(f"Daily tab: wrote {len(rows)} jobs (sorted by confidence desc)")
```

- [ ] **Step 4.4: Run the tests to verify they pass**

Run: `pytest tests/test_daily_sponsorship.py tests/test_daily_columns.py -v`
Expected: All tests PASS (5 label tests + 6 row-shape tests + 5 column-order tests = 16 total).

- [ ] **Step 4.5: Commit**

```bash
git add tests/test_daily_sponsorship.py sheets/daily.py
git commit -m "feat: wire daily.py row builder to new 15-column order"
```

---

## Task 5: Update `sheets/formatting.py` widths and header count

**Files:**
- Modify: `sheets/formatting.py:63-113` (the `format_daily` function)

This task has no unit test — formatting is verified manually because the assertions involve gspread's batch_update behavior. Trust the explicit width array layout.

- [ ] **Step 5.1: Update `format_daily` in `sheets/formatting.py`**

In `sheets/formatting.py`, in the `format_daily` function, replace the `widths = [...]` block (lines 73-91) AND the `_header_format(sheet_id, 14)` call (line 71) AND the comment on line 71-72:

Old:
```python
    # Header style: dark navy bg, white bold text (14 columns incl. Posted)
    requests.append(_header_format(sheet_id, 14))

    # Column widths — Apply Link is right after Status
    widths = [
        (0, 160),   # Company
        (1, 220),   # Job Title
        (2, 150),   # Location
        (3, 90),    # Confidence
        (4, 90),    # Status
        (5, 250),   # Apply Link
        (6, 90),    # Posted  (e.g. "3h ago")
        (7, 130),   # Source
        (8, 300),   # AI Reasoning
        (9, 140),   # Suggested Angle
        (10, 180),  # Match Signals
        (11, 180),  # Risk Flags
        (12, 120),  # Salary Range
        (13, 150),  # Notes
    ]
```

New:
```python
    # Header style: dark navy bg, white bold text (15 columns)
    requests.append(_header_format(sheet_id, 15))

    # Column widths — Risk Flags after Status, Sponsorship before Salary
    widths = [
        (0, 160),   # Company
        (1, 220),   # Job Title
        (2, 150),   # Location
        (3, 90),    # Confidence
        (4, 90),    # Status
        (5, 180),   # Risk Flags
        (6, 250),   # Apply Link
        (7, 90),    # Posted (e.g. "3h ago")
        (8, 130),   # Source
        (9, 300),   # AI Reasoning
        (10, 140),  # Suggested Angle
        (11, 180),  # Match Signals
        (12, 130),  # Sponsorship
        (13, 120),  # Salary Range
        (14, 150),  # Notes
    ]
```

The existing dropdown and conditional format calls (`_data_validation` on `col=4`, `_cond_format_text` on `col=4`, `_cond_format_number` on `col=3`) all reference Status and Confidence columns whose indices are unchanged — leave them as-is.

- [ ] **Step 5.2: Run the existing test suite to ensure nothing regresses**

Run: `pytest tests/ -v 2>&1 | tail -30`
Expected: All previously-passing tests still PASS.

- [ ] **Step 5.3: Commit**

```bash
git add sheets/formatting.py
git commit -m "feat: update Daily tab formatting for 15-column layout"
```

---

## Task 6: Remove `no_h1b_history` injection from Stage 2 fallbacks

**Files:**
- Modify: `screening/stage2.py:183-203` (the `_default_apply` and `_default_maybe` methods)
- Modify: `prompts/screening.md` (line 37)

- [ ] **Step 6.1: Add a regression test**

Append to `tests/test_stage2.py` — at the end of the file, add:

```python
def test_default_apply_does_not_inject_no_h1b_history_flag():
    """no_h1b_history was a risk flag; sponsorship now has its own column."""
    from models.job import RawJob
    from screening.stage2 import Stage2Screen

    job = RawJob(
        title="Cloud Engineer",
        company="Acme",
        location="Remote",
        url="https://example.com",
        source="linkedin",
        h1b_sponsor_verified=False,  # would have triggered the flag previously
    )
    screened = Stage2Screen()._default_apply(job)
    assert "no_h1b_history" not in screened.risk_flags


def test_default_maybe_does_not_inject_no_h1b_history_flag():
    from models.job import RawJob
    from screening.stage2 import Stage2Screen

    job = RawJob(
        title="Cloud Engineer",
        company="Acme",
        location="Remote",
        url="https://example.com",
        source="linkedin",
        h1b_sponsor_verified=False,
    )
    screened = Stage2Screen()._default_maybe(job)
    assert "no_h1b_history" not in screened.risk_flags
```

- [ ] **Step 6.2: Run the new tests to verify they fail**

Run: `pytest tests/test_stage2.py -v -k "no_h1b_history"`
Expected: 2 FAIL — the current fallbacks inject `["no_h1b_history"]` when `h1b_sponsor_verified is False`.

- [ ] **Step 6.3: Update `_default_apply` in `screening/stage2.py`**

In `screening/stage2.py`, replace `_default_apply` (lines 183-192):

Old:
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

New:
```python
    def _default_apply(self, job: RawJob) -> ScreenedJob:
        return ScreenedJob(
            **job.model_dump(),
            verdict=ScreeningVerdict.APPLY,
            confidence=2,
            reasoning="Claude screening failed — defaulting to APPLY for manual review",
            suggested_angle="",
            risk_flags=[],
        )
```

- [ ] **Step 6.4: Update `_default_maybe` in `screening/stage2.py`**

Replace `_default_maybe` (lines 194-203):

Old:
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

New:
```python
    def _default_maybe(self, job: RawJob) -> ScreenedJob:
        return ScreenedJob(
            **job.model_dump(),
            verdict=ScreeningVerdict.MAYBE,
            confidence=2,
            reasoning="Not returned in Claude screening batch — flagged for review",
            suggested_angle="",
            risk_flags=[],
        )
```

- [ ] **Step 6.5: Update the screening prompt**

In `prompts/screening.md`, replace line 37:

Old:
```
If h1b_sponsor_verified is false: add "no_h1b_history" to risk_flags and reduce confidence by 1 (minimum 1). Do not auto-SKIP on this signal alone.
```

New:
```
If h1b_sponsor_verified is false: reduce confidence by 1 (minimum 1). Do NOT add "no_h1b_history" to risk_flags — sponsorship state has its own column. Do not auto-SKIP on this signal alone.
```

- [ ] **Step 6.6: Run the tests to verify they pass**

Run: `pytest tests/test_stage2.py -v`
Expected: All tests PASS, including the 2 new no_h1b_history regression tests.

- [ ] **Step 6.7: Commit**

```bash
git add screening/stage2.py prompts/screening.md tests/test_stage2.py
git commit -m "refactor: remove no_h1b_history risk flag (now in Sponsorship column)"
```

---

## Task 7: Move H1B Sponsor Check to Phase 5 in `main.py`

**Files:**
- Modify: `main.py` (the docstring header, Phase 5 / Phase 7 blocks, and the final summary stats dict)

This is the most involved task. The H1B check moves from Phase 7 to Phase 5. Phase 5 (current) and Phase 6 (current) shift to become Phases 6 and 7. Phase 7's H1B logic gets enhanced with `partition_drops` and an Audit write for dropped jobs.

- [ ] **Step 7.1: Update the docstring header in `main.py`**

Replace lines 1-16 of `main.py`:

Old:
```python
"""
============================================================
  INTELLIGENT JOB SEARCH — Main Pipeline
============================================================
  1.  Init (creds + profile + DB)
  2.  Clear Daily + Audit tabs
  3.  Parallel scrape all sources
  4.  Freshness filter (<= HOURS_OLD)
  5.  Backfill descriptions for no-desc jobs
  6.  Stage 1 regex filter
  7.  H1B Sponsor Check
  8.  Persist to SQLite
  9.  Stage 2 Claude CLI precision screen
  10. Write to Daily + Audit
============================================================
"""
```

New:
```python
"""
============================================================
  INTELLIGENT JOB SEARCH — Main Pipeline
============================================================
  1.  Init (creds + profile + DB)
  2.  Clear Daily + Audit tabs
  3.  Parallel scrape all sources
  4.  Freshness filter (<= HOURS_OLD)
  5.  H1B Sponsor Check + source-aware drop
  6.  Backfill descriptions for no-desc jobs
  7.  Stage 1 regex filter
  8.  Persist to SQLite
  9.  Stage 2 Claude CLI precision screen
  10. Write to Daily + Audit
============================================================
"""
```

- [ ] **Step 7.2: Update import in `main.py`**

In `main.py` line 36, the existing import is:
```python
from screening.h1b_checker import H1BChecker
```

Change to:
```python
from screening.h1b_checker import H1BChecker, partition_drops
```

- [ ] **Step 7.3: Delete the existing Phase 7 block from `main.py`**

In `main.py`, delete the existing Phase 7 block (lines 210-223 — the `# ── Phase 7: H1B Sponsor Check ───` block, including the blank line that follows). It will be re-added in the new position in Step 7.4.

- [ ] **Step 7.4: Insert the new Phase 5 block in `main.py`**

Locate the end of the current Phase 4 block in `main.py` (immediately after `ui.phase_done(f"kept {len(unique_jobs)}  ·  dropped {len(stale_jobs)} stale")`). Replace the next section (which is currently `# ── Phase 5: Backfill descriptions ────────────────────────`) so the order becomes: H1B check first, then backfill.

Insert this NEW block immediately after the Phase 4 block, BEFORE the Backfill block:

```python
    # ── Phase 5: H1B Sponsor Check + source-aware drop ───────
    ui.phase(5, "H1B Sponsor Check + source-aware drop")
    checker = H1BChecker(db)
    await checker.check_batch(unique_jobs)
    n_curated = sum(
        1 for j in unique_jobs
        if j.source.startswith(("greenhouse-", "lever-", "ashby-"))
    )
    n_verified = sum(1 for j in unique_jobs if j.h1b_sponsor_verified is True)
    sponsor_kept, sponsor_dropped = partition_drops(unique_jobs)
    n_checked = sum(1 for j in unique_jobs if j.h1b_sponsor_verified is not None)
    n_no_history_kept = sum(
        1 for j in sponsor_kept if j.h1b_sponsor_verified is False
    )
    unique_jobs = sponsor_kept  # rebind for downstream phases

    # Persist dropped jobs to Audit so the funnel is auditable
    if sponsor_dropped:
        today_str = date.today().isoformat()
        h1b_audit_entries = [
            {
                "job_fingerprint": j.fingerprint,
                "company": j.company,
                "title": j.title,
                "source": j.source,
                "stage": "stage_h1b",
                "verdict": "REJECT",
                "reason": "company has no H-1B sponsorship history",
                "confidence": None,
                "run_date": today_str,
            }
            for j in sponsor_dropped
        ]
        db.save_audit_entries_bulk(h1b_audit_entries)

        h1b_drop_results = [
            type("FilterResult", (), {
                "job": j,
                "stage": "stage_h1b",
                "reason": "company has no H-1B sponsorship history",
                "passed": False,
            })()
            for j in sponsor_dropped
        ]
        audit_ops.write_rejections(audit_ws, h1b_drop_results)

    ui.phase_done(
        f"{n_checked} checked  ·  {n_verified} verified  ·  "
        f"{len(sponsor_dropped)} no-history dropped  ·  "
        f"{n_no_history_kept} no-history kept (startup-friendly)  ·  "
        f"{n_curated} curated skipped"
    )
```

- [ ] **Step 7.5: Renumber the remaining phases in `main.py`**

Starting from where Backfill currently lives, renumber `ui.phase(N, ...)` calls so the order matches:

| Old phase number | New phase number | Block |
|---|---|---|
| 5 | 6 | Backfill descriptions |
| 6 | 7 | Stage 1 regex filter |
| 7 | (deleted — moved up) | (was H1B Sponsor Check) |
| 8 | 8 | Persist to SQLite |
| 9 | 9 | Stage 2 Claude screen |
| 10 | 10 | Write Daily + Audit |

For each block, update both the `ui.phase(N, ...)` line at the start AND the comment header (e.g., `# ── Phase 5: Backfill descriptions ───` becomes `# ── Phase 6: Backfill descriptions ───`).

Specifically:
- Find `ui.phase(5, "Backfilling missing descriptions")` → change `5` to `6`. Update the comment header to `# ── Phase 6: Backfill descriptions ──────────────────────`.
- Find `ui.phase(6, "Stage 1 regex filter")` → change `6` to `7`. Update the comment header to `# ── Phase 7: Stage 1 regex filter ─────────────────────`.
- Phases 8, 9, 10 keep their numbers (Persist, Stage 2, Write).

- [ ] **Step 7.6: Update the final summary stats dict in `main.py`**

In `main.py`, locate the `stats = { ... }` block (around line 344) and add the new key. Replace:

Old:
```python
    stats = {
        # ── Scrape funnel ──────────────────────────────────────
        "Scraped (all sources)": len(all_scraped),
        f"Fresh (<= {HOURS_OLD}h)": len(unique_jobs),
        "Stale dropped": len(stale_jobs),
```

New:
```python
    stats = {
        # ── Scrape funnel ──────────────────────────────────────
        "Scraped (all sources)": len(all_scraped),
        f"Fresh (<= {HOURS_OLD}h)": len(unique_jobs) + len(sponsor_dropped),
        "Stale dropped": len(stale_jobs),
        "Dropped (no h1b sponsor)": len(sponsor_dropped),
```

The Fresh count is restored to the pre-drop number so the funnel stays honest about what came out of Phase 4 vs. what was dropped in Phase 5.

- [ ] **Step 7.7: Run the full test suite**

Run: `pytest tests/ -v 2>&1 | tail -20`
Expected: All tests PASS. Note: there is no main.py unit test — this is verified via tests of the components and a manual smoke test in Task 9.

- [ ] **Step 7.8: Commit**

```bash
git add main.py
git commit -m "feat: move H1B check to Phase 5 with source-aware drop + audit"
```

---

## Task 8: Verify and clean up `tests/test_stage2.py` for old assertions

**Files:**
- Modify: `tests/test_stage2.py` (audit existing tests)

The existing test_stage2.py was written before the no_h1b_history flag was removed. Some tests may explicitly assert the flag's presence in fallback paths.

- [ ] **Step 8.1: Search for any remaining `no_h1b_history` references**

Run:
```
grep -rn "no_h1b_history" tests/
```

Expected: Zero hits OUTSIDE the two new regression tests added in Task 6 (`test_default_apply_does_not_inject_no_h1b_history_flag`, `test_default_maybe_does_not_inject_no_h1b_history_flag`).

If you find ANY other test asserting the flag is *present* in `risk_flags`, delete that assertion line (it tested behavior we're intentionally removing).

- [ ] **Step 8.2: Run the full test suite**

Run: `pytest tests/ -v 2>&1 | tail -20`
Expected: All tests PASS.

- [ ] **Step 8.3: Commit (only if files changed)**

```bash
git status
# If tests/test_stage2.py shows changes:
git add tests/test_stage2.py
git commit -m "test: remove obsolete no_h1b_history assertions"
# Otherwise skip the commit.
```

---

## Task 9: Manual smoke test + final verification

**Files:** none — this is verification only.

- [ ] **Step 9.1: Run the full test suite end-to-end**

Run: `pytest tests/ -v 2>&1 | tail -30`
Expected: All tests PASS, no warnings about deprecated assertions.

Confirm pytest exit code is 0:
```
echo $?
```
Expected: `0`

- [ ] **Step 9.2: Type-check the modified files**

Run:
```
python -m py_compile config.py main.py screening/h1b_checker.py screening/stage2.py sheets/daily.py sheets/formatting.py
```
Expected: No output (success).

- [ ] **Step 9.3: Manual run of the pipeline against live Sheets**

Run: `python main.py`
Expected behavior to verify by eye:
1. Phase 5 log line shows the new format: `N checked · N verified · N no-history dropped · N no-history kept · N curated skipped`.
2. Final summary panel includes `Dropped (no h1b sponsor)` between `Stale dropped` and `With descriptions`.
3. Daily tab in Google Sheets shows 15 columns:
   - Risk Flags is at column F (index 5), right after Status.
   - Sponsorship is at column M (index 12), between Match Signals and Salary Range.
   - For at least one verified-sponsor job (e.g., a known sponsor like Anthropic, Stripe, or Google) the Sponsorship cell reads "Verified sponsor".
   - For at least one curated ATS job (greenhouse-/lever-/ashby- source) with no H1B record, the Sponsorship cell reads "Curated — unknown".
4. Audit tab includes new rows with reason `company has no H-1B sponsorship history` for any dropped jobs from LinkedIn/Indeed/Google/Workday.
5. Compare runtime to the 7.5h baseline — log Phase 5 timing in particular. If Phase 5 takes more than ~10 minutes on first run, that's expected (cache warming); subsequent runs should be sub-minute.

- [ ] **Step 9.4: If smoke test passes, no further commits needed**

The implementation is complete. If something visual is off (e.g., column width too narrow), fix and commit:

```bash
git add sheets/formatting.py
git commit -m "fix: tweak Daily tab column widths after manual review"
```

If the smoke test reveals a logic bug (e.g., partition_drops is dropping the wrong jobs), STOP and re-open the relevant task — do not patch over it.

---

## Self-review checklist

**Spec coverage:**
- ✅ "Move H1B check from Phase 7 to Phase 5" → Task 7
- ✅ "Source-aware drop (LinkedIn/Indeed/Google/Workday vs HN/RemoteOK/curated)" → Task 1
- ✅ "Add Sponsorship column" → Tasks 2, 3, 4
- ✅ "Move Risk Flags to col 6" → Tasks 3, 4, 5
- ✅ "Drop bucket logs to Audit with reason" → Task 7
- ✅ "Remove no_h1b_history risk flag from stage2 fallbacks + prompt" → Task 6
- ✅ "Update final summary panel with new stat" → Task 7
- ✅ "Phase log line format" → Task 7

**Type consistency:**
- `partition_drops` returns `tuple[list[RawJob], list[RawJob]]` in both Task 1 implementation and Task 7 caller — consistent.
- `_sponsorship_label` accepts `ScreenedJob` and returns `str` — consistent across Tasks 2 and 4.
- `is_droppable_source` accepts `str`, returns `bool` — used only by `partition_drops` internally.

**No placeholders:** all code blocks contain complete, runnable code; no TBDs or "similar to" references.
