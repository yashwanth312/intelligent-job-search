# Sponsorship Pipeline Redesign

**Date:** 2026-04-29
**Status:** Design approved, awaiting implementation plan

## Goal

Cut pipeline runtime (currently ~7.5 hours) and surface sponsorship signal more clearly in the Daily tab. The user is on OPT with authorization expiring in roughly 2 months; speed of iteration *and* not missing sponsoring startups are both critical.

## Three changes

1. **Move H1B Sponsor Check from Phase 7 to Phase 5** so non-sponsor jobs from big-company sources are dropped *before* description backfill (the slowest phase) and Stage 2 Claude screening (the second-slowest).
2. **Add a dedicated `Sponsorship` column** to the Daily tab. The existing `no_h1b_history` risk flag is removed; sponsorship state lives in its own column.
3. **Move the `Risk Flags` column** to position 6 (right after Status) so risk signals are visible without scrolling.

## Approach: source-aware drop

h1bdata.info only lists companies that have *already filed* H1B petitions. A young startup that *would* sponsor but hasn't yet is invisible. So `verified=False` is a noisy signal — informative for big companies, near-useless for startups.

We resolve this by partitioning sources by their startup likelihood:

- **Drop bucket** — sources that skew toward established companies, where `verified=False` strongly indicates "won't sponsor":
  - exact match: `linkedin`, `indeed`, `google`
  - prefix match: `workday-*` (per-tenant adapters emit `workday-{tenant}`)
- **Keep bucket** — sources that skew toward startups or are user-curated, where we want benefit of the doubt:
  - `hackernews`, `remoteok`, `greenhouse-*`, `lever-*`, `ashby-*`

For drop-bucket sources with `verified=False`, the job is dropped from the pipeline at Phase 5 and logged to the Audit tab with reason `"company has no H-1B sponsorship history"`. All other combinations pass through to Phase 6 (backfill).

## Pipeline order (after redesign)

```
Phase 1:  Init
Phase 2:  Clear Daily + Audit
Phase 3:  Scrape sources (parallel)
Phase 4:  Freshness filter (<= HOURS_OLD)
Phase 5:  H1B Sponsor Check + source-aware drop      ← MOVED FROM PHASE 7
Phase 6:  Backfill descriptions                       (smaller pool)
Phase 7:  Stage 1 regex filter
Phase 8:  Persist to SQLite
Phase 9:  Stage 2 Claude precision screen             (smaller pool)
Phase 10: Write Daily + Audit
```

`TOTAL_PHASES` stays at 10. The H1B checker operates on a larger pool than before (post-Freshness instead of post-Stage-1), so the first run after deploy will scrape h1bdata.info more aggressively. Subsequent runs benefit from the warmer cache (30-day TTL, unchanged).

## Daily tab schema

New column order — 15 columns total (was 14):

| # | Column | Notes |
|---|---|---|
| 1 | Company | unchanged |
| 2 | Job Title | unchanged |
| 3 | Location | unchanged |
| 4 | Confidence | unchanged |
| 5 | Status | unchanged |
| **6** | **Risk Flags** | **moved up from col 12** |
| 7 | Apply Link | unchanged |
| 8 | Posted | unchanged |
| 9 | Source | unchanged |
| 10 | AI Reasoning | unchanged |
| 11 | Suggested Angle | unchanged |
| 12 | Match Signals | unchanged |
| **13** | **Sponsorship** | **new** |
| 14 | Salary Range | unchanged |
| 15 | Notes | unchanged |

### Sponsorship label derivation

```python
def _sponsorship_label(job: ScreenedJob) -> str:
    if job.h1b_sponsor_verified is True:
        return "Verified sponsor"
    if job.h1b_sponsor_verified is False:
        return "No H-1B history"
    if job.source.startswith(("greenhouse-", "lever-", "ashby-")):
        return "Curated — unknown"
    return ""
```

`verified=False` only reaches this label for jobs *kept* by the source-aware drop (i.e., HN, RemoteOK, or curated ATS). Drop-bucket sources with `verified=False` never reach the Daily tab — they go to Audit.

## Code touch points

| File | Change |
|---|---|
| `config.py` | `DAILY_HEADERS` reordered + `Sponsorship` added (15 entries) |
| `main.py` | Move H1B check to Phase 5; partition into kept/dropped; log dropped jobs to Audit; renumber phase docstrings/labels; update final-summary stat keys |
| `screening/h1b_checker.py` | Add `is_droppable_source(source: str) -> bool` returning True for `linkedin`, `indeed`, `google`, `workday`. Add `partition_drops(jobs) -> (kept, dropped)` based on source + `h1b_sponsor_verified` |
| `sheets/daily.py` | Add `_sponsorship_label(job)`; row builder writes 15 columns in new order |
| `sheets/formatting.py` | `widths[]` rebuilt for 15 cols; `_header_format(..., 15)`; Status dropdown still col 4; cond-format indices unchanged |
| `screening/stage2.py` | Remove `no_h1b_history` injection from `_default_apply` (line 184) and `_default_maybe` (line 195) |
| `prompts/screening.md` | Remove instruction (if any) telling Claude to add `no_h1b_history` to `risk_flags` |
| `tests/test_orchestrator.py` and related tests | Update fixtures referencing old column count or `no_h1b_history` risk flag |

### Phase 5 log line (new format)

```
Phase 5: H1B check + source-aware drop
  N checked · N verified sponsors · N no-history (dropped) · N kept (startup-friendly) · N curated skipped
```

### Final summary panel — new stat

A new key `"Dropped (no h1b sponsor)"` is added between `"Stale dropped"` and `"With descriptions"` so the funnel reflects the new filter.

## Audit tab integration

Dropped jobs in Phase 5 use the existing `Database.save_audit_entries_bulk` and `audit_ops.write_rejections` paths. Audit row fields:

- `stage`: `"stage_h1b"` (new stage value)
- `verdict`: `"REJECT"`
- `reason`: `"company has no H-1B sponsorship history"`

No schema changes to the Audit tab — current headers (`Company`, `Job Title`, `Killed At`, `Reason`, `Source`, `Apply Link`) accommodate the new entries.

## Testing plan

### New unit tests

- `tests/test_h1b_partition.py`
  - `verified=False` from `linkedin` / `indeed` / `google` / `workday` → dropped bucket
  - `verified=False` from `hackernews` / `remoteok` / `greenhouse-acme` / `lever-foo` / `ashby-bar` → kept bucket
  - `verified=True` from any source → kept
  - `verified=None` from any source → kept
- `tests/test_daily_sponsorship_column.py`
  - `verified=True` → `"Verified sponsor"`
  - `verified=False` → `"No H-1B history"`
  - `verified=None` + curated source → `"Curated — unknown"`
  - `verified=None` + non-curated source → `""`
- `tests/test_daily_column_order.py`
  - `DAILY_HEADERS` matches expected list
  - Each row written by `write_screened_jobs` has 15 cells
  - Position 6 is Risk Flags; position 13 is Sponsorship

### Updated tests

- `tests/test_orchestrator.py` — update any fixture asserting column count/order.
- Any test asserting `no_h1b_history` appears in `risk_flags` — assert absence; check sponsorship state instead.

### Manual verification before declaring done

1. `pytest tests/ -v` — all green.
2. Run a small `python main.py` against a live Sheets doc with 1–2 known sponsoring companies and 1–2 known non-sponsors. Verify:
   - Daily tab has 15 columns in correct order
   - Sponsorship column shows correct labels
   - Dropped jobs appear in Audit with the new reason text
3. Eyeball the final summary panel — `"Dropped (no h1b sponsor)"` is visible and non-zero.
4. Compare runtime against the previous 7.5h baseline — log Phase 5 timing.

## Out of scope (deliberately deferred)

- **Manual blocklist** (Approach B from brainstorming) — defer until we see whether Approach A is too aggressive.
- **Re-checking expired cache entries during Phase 5** — current 30-day TTL is sufficient; orthogonal concern.
- **Heuristic startup detection** (Approach C from brainstorming) — defer unless Approach A drops too aggressively in practice.
- **Whitelist override** in `config.py` — discussed and dropped; revisit only if a known-good startup gets filtered.
