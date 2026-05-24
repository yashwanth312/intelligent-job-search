# Pipeline Reliability Fixes — Design Spec
**Date:** 2026-05-23
**Status:** Approved

## Background

A live monitoring session on 2026-05-23 revealed 7 issues across the pipeline ranging from silent data loss risk to missing observability. This spec covers fixes for all critical, high, and medium severity issues identified. LinkedIn timeout was explicitly excluded — the user wants LinkedIn to always run to completion regardless of duration.

---

## Scope

7 fixes across 8 files:

| # | Severity | Fix | Files Touched |
|---|---|---|---|
| 1 | High | Stage 2 silent batch drop warning | `screening/stage2.py` |
| 2 | High | Google Sheets writes with retry | `sheets/daily.py`, `sheets/audit.py` |
| 3 | High | H1B checker wall-clock timeout | `main.py` |
| 4 | Medium | Workday dedup before Daily write | `main.py` |
| 5 | Medium | Config validation at startup | `config.py`, `main.py` |
| 6 | Medium | Remove stale Coinbase token | `target_companies.yaml` |
| 7 | Medium | Per-source failure count in Phase 3 summary | `sources/orchestrator.py`, `main.py` |

---

## Fix 1 — Stage 2 Silent Batch Drop Warning

**File:** `screening/stage2.py:screen_batch`

**Problem:** When Claude CLI returns fewer results than jobs submitted (partial batch response, JSON parse failure, timeout), the missing jobs silently receive `_default_maybe()` verdict with reason "Not returned in Claude screening batch". There is no warning, no count, and no way to know how many jobs were quietly downgraded during a run.

**Design:** After building `result_map` from the batch response, compare `len(result_map)` to `len(batch)`. If any are missing, log a `WARNING` that includes:
- Batch index (which batch failed)
- Count returned vs submitted (e.g. `3/5 returned`)
- Titles of the missing jobs (for traceability)

The fallback behavior (`_default_maybe`) is unchanged — this is observability only.

```python
missing = [j for j in batch if j.fingerprint not in result_map]
if missing:
    titles = ", ".join(j.title for j in missing)
    logger.warning(
        f"Stage 2 batch {i // SCREENING_BATCH_SIZE + 1}: "
        f"{len(result_map)}/{len(batch)} returned — "
        f"defaulting to MAYBE for: {titles}"
    )
```

**Impact:** Zero change to job quantity or filter quality.

---

## Fix 2 — Google Sheets Writes With Retry

**Files:** `sheets/daily.py`, `sheets/audit.py`

**Problem:** `ws.append_rows()` in both files has no retry. A transient Google Sheets API error (quota exceeded, network blip, 500) silently loses the write — results are in SQLite but the Daily/Audit tabs are empty with no clear error surfaced to the user.

**Design:** Add a shared private helper `_append_rows_with_retry(ws, rows, value_input_option, max_attempts=3, backoff_base=2.0)` in a new `sheets/_retry.py`. Both `write_screened_jobs` (daily.py) and `write_rejections` (audit.py) call this helper instead of `ws.append_rows()` directly.

Retry logic:
- Catch `Exception` broadly (gspread raises various subtypes for quota/network errors)
- On failure: log a warning with attempt number and error, sleep `backoff_base ** attempt` seconds (2s, 4s)
- After `max_attempts` exhausted: log an ERROR with explicit message: `"Google Sheets write failed after {max_attempts} attempts — results are in SQLite but not visible in Sheets"`
- Re-raise on final failure so the caller knows

**Impact:** Zero change to job quantity or filter quality. Only affects write reliability.

---

## Fix 3 — H1B Checker Wall-Clock Timeout

**File:** `main.py:Phase 5`

**Problem:** `await checker.check_batch(unique_jobs)` has no wall-clock timeout. If the h1bdata.info endpoint hangs (not times out at the individual request level but stalls at the session/connection level), the entire pipeline blocks indefinitely.

**Design:** Wrap with `asyncio.wait_for(..., timeout=300)` (5 minutes). On `asyncio.TimeoutError`:
- Log a `WARNING`: `"H1B checker timed out after 300s — all jobs proceeding with h1b_sponsor_verified=None"`
- Continue pipeline normally

**Behavior on timeout:** All jobs keep `h1b_sponsor_verified=None`. `partition_drops()` treats `None` as kept (not dropped), so the pipeline continues with more jobs in the funnel rather than fewer. This is the safe failure direction — review more, miss nothing.

The individual request timeout (10s via `aiohttp.ClientTimeout`) is already in place in `h1b_checker.py:_scrape_year`. The 300s wall-clock is a safety net for hangs above the request level.

**Impact on normal runs:** None — the timeout only fires if the checker genuinely hangs. On timeout, slightly more jobs flow through Stage 1/2 (conservative direction).

---

## Fix 4 — Workday Dedup Before Daily Write

**File:** `main.py:Phase 9`

**Problem:** `daily_jobs` is assembled from two sources:
1. Screened jobs from Stage 2 (APPLY/MAYBE verdicts)
2. Unscreened no-desc passthrough jobs (MAYBE, confidence=1)

If a Workday job had its description filled during Phase 6, it was removed from `no_desc_passed` via the `filled_fps` filter. However, the filter only covers `wd_filled_jobs` — if a Workday job appeared in both `desc_jobs` and `no_desc_passed` via a different path, it could end up in `daily_jobs` twice.

**Design:** Just before calling `daily_ops.write_screened_jobs()`, deduplicate `daily_jobs` by fingerprint. When a fingerprint appears twice, keep the screened Stage 2 version (higher confidence, has reasoning) and discard the unscreened MAYBE. Log a warning if any duplicates are removed.

```python
seen_fps: set[str] = set()
deduped: list[ScreenedJob] = []
for job in sorted(daily_jobs, key=lambda j: j.confidence, reverse=True):
    if job.fingerprint not in seen_fps:
        seen_fps.add(job.fingerprint)
        deduped.append(job)
    else:
        logger.warning(f"Dedup: removed duplicate daily entry for {job.company} — {job.title}")
daily_jobs = deduped
```

**Impact:** May reduce Daily tab count by the number of duplicates (typically 0, at most a handful). Quality improves — screened verdict is shown instead of unscreened MAYBE.

---

## Fix 5 — Config Validation at Startup

**Files:** `config.py`, `main.py:Phase 1`

**Problem:** Missing `.env` values silently produce empty strings. `YOUR_NAME=""`, `YOUR_EMAIL=""`, missing `credentials.json` — the pipeline runs all 7 phases before failing with an unhelpful error deep in gspread or generation code.

**Design:** Add `validate_required_config()` to `config.py`:

```python
def validate_required_config() -> None:
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

Called at the top of Phase 1 in `main.py`, before DB/Sheets initialization. Fails immediately with a clear human-readable message.

**Impact:** Zero impact on runs with valid config. Fast-fail only.

---

## Fix 6 — Remove Stale Coinbase Token

**File:** `target_companies.yaml`

**Problem:** Coinbase's Greenhouse token is returning HTTP 404 on every run, logged as `WARNING Greenhouse Coinbase: HTTP 404`. The company contributes 0 jobs but adds noise to every log.

**Design:** Remove Coinbase from the `greenhouse` list in `target_companies.yaml`.

**Impact:** Zero — Coinbase was already returning 0 jobs.

---

## Fix 7 — Per-Source Failure Count in Phase 3 Summary

**Files:** `sources/orchestrator.py`, `main.py`

**Problem:** The Phase 3 scrape table shows `✓` for every source including ones that fully failed (e.g., LinkedIn DNS failures show the count jobspy managed to return before exhausting retries, with no explicit failure flag). The Phase 3 `ui.phase_done()` line doesn't mention source errors at all. Failures only appear in the final stats panel as `"Source errors: N (see log)"`.

**Design (two-part):**

**Part A — `orchestrator.py`:** Track which adapter names had errors. After `asyncio.gather`, collect `failed_sources = [adapter.name for adapter, result in zip(self.adapters, results) if result.errors]`. Include in the returned `SourceResult` or surface via the existing `errors` list (already populated).

**Part B — `main.py`:** In the Phase 3 `ui.phase_done()` call, check `scrape_result.errors` and append a failure note:
```python
error_note = f"  ·  {len(scrape_result.errors)} source error(s)" if scrape_result.errors else ""
ui.phase_done(f"{len(all_scraped)} unique jobs after dedup{error_note}")
```

This surfaces failures in the live phase-by-phase output, not just the final stats panel.

**Impact:** Zero change to scraping quantity or filter quality. Observability only.

---

## Files Changed Summary

| File | Changes |
|---|---|
| `screening/stage2.py` | Add batch drop warning in `screen_batch` |
| `sheets/_retry.py` | New file — `_append_rows_with_retry` helper |
| `sheets/daily.py` | Use `_append_rows_with_retry` |
| `sheets/audit.py` | Use `_append_rows_with_retry` |
| `main.py` | H1B timeout wrapper, Workday dedup, config validation call, Phase 3 error note |
| `config.py` | Add `validate_required_config()` |
| `target_companies.yaml` | Remove Coinbase entry |
| `sources/orchestrator.py` | Surface failed source names in error note |

---

## What Is NOT Changed

- LinkedIn scraping behavior — runs to completion regardless of duration (by design)
- Stage 2 fallback logic — `_default_maybe()` behavior is unchanged
- Job fingerprinting, deduplication, or freshness filtering
- H1B drop logic — `partition_drops()` is unchanged
- Any Stage 1 filter rules
- Sheets column structure or formatting
