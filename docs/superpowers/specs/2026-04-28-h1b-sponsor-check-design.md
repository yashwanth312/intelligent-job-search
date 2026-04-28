# H1B Sponsor Check — Design Spec

**Date:** 2026-04-28
**Status:** Approved

## Problem

Jobs scraped from open sources (LinkedIn, Indeed, HackerNews, RemoteOK, Workday) pass through
the pipeline as long as they do not explicitly say "no sponsorship" in the description. Most
companies that won't sponsor simply stay silent about it, so non-sponsoring companies reach the
Daily tab and create noise. Curated sources (Greenhouse/Lever/Ashby) are pre-vetted in
`target_companies.yaml`, but open-source companies have no such gate.

## Goal

For every company from an open source that survives Stage 1, check whether it has filed any
H1B LCA applications in the current or previous calendar year. Companies with no recent filings
get a `no_h1b_history` risk flag and a confidence penalty in Stage 2. Nothing is hard-rejected
purely on this signal — the user still sees these jobs but they are visually demoted.

## Approach

New Phase 7 in the pipeline (total phases: 9 → 10), sitting between Stage 1 and the SQLite
persist. Results are cached in SQLite with a 30-day TTL so each company is only looked up once
per month. Claude receives the signal in the Stage 2 prompt and incorporates it into reasoning
and risk flags.

## Pipeline

```
Phase 1   Init
Phase 2   Clear sheets
Phase 3   Scrape
Phase 4   Freshness filter
Phase 5   Backfill descriptions
Phase 6   Stage 1 regex filter
Phase 7   H1B Sponsor Check          ← new
Phase 8   Persist to SQLite
Phase 9   Stage 2 Claude screen
Phase 10  Write Daily + Audit
```

## Components

### `screening/h1b_checker.py` (new)

**Class:** `H1BChecker(db: Database)`

**Public interface:**
```python
async def check_batch(self, jobs: list[RawJob]) -> None
```
Mutates `h1b_sponsor_verified` in-place on each job. Curated-source jobs (`source` starts with
`greenhouse-`, `lever-`, or `ashby-`) are skipped — their field remains `None`.

**Company name normalization:**
Strip legal suffixes (inc, llc, corp, ltd, co, lp, plc, incorporated, limited) as whole words,
case-insensitive. Lowercase. Strip punctuation. Collapse whitespace. Result is the `company_key`
used for cache lookups.

Examples:
- `"Stripe, Inc."` → `"stripe"`
- `"Meta Platforms LLC"` → `"meta platforms"`
- `"ServiceNow"` → `"servicenow"`

**Lookup flow per unique company:**
1. Check `h1b_sponsor_cache` — if hit and age < `H1B_CACHE_TTL_DAYS` (30), return cached value.
2. On miss or expiry: scrape h1bdata.info for current year and previous year concurrently.
3. If either year returns ≥ 1 result row → `verified = True`.
4. If both return 0 rows → `verified = False`.
5. Store result (even `False`) in cache with current UTC timestamp.
6. On any exception (timeout, HTTP error, parse failure) → return `None`; do not flag the job.

**h1bdata.info requests:**
```
GET https://h1bdata.info/index.php?em=<URL-ENCODED-NAME>&job=&city=&year=<YEAR>
```
Two requests per company: current calendar year and previous calendar year.
Parse the HTML response table — presence of any `<tr>` data rows indicates filings exist.

**Concurrency:** `asyncio.gather` with a semaphore of 3. Each request timeout: 10s.
Uses `aiohttp` (already a project dependency).

**Deduplication:** Multiple jobs from the same company produce a single lookup. All jobs sharing
that company get the same result applied.

### `models/job.py`

Add one field to `RawJob`:
```python
h1b_sponsor_verified: bool | None = None
# None  = not checked (curated source or lookup errored)
# True  = has H1B filings in current or previous calendar year
# False = no filings found in either year
```
`ScreenedJob` inherits it automatically.

### `db/database.py`

**New table** (added to `_create_tables()`):
```sql
CREATE TABLE IF NOT EXISTS h1b_sponsor_cache (
    company_key  TEXT PRIMARY KEY,
    company_raw  TEXT NOT NULL,
    verified     INTEGER NOT NULL,   -- 1 = sponsor, 0 = no history
    checked_at   TEXT NOT NULL       -- ISO-8601 UTC
);
```

**New methods on `Database`:**
- `get_h1b_cache(company_key: str) -> bool | None`
  Returns cached `verified` bool if `checked_at` is within `H1B_CACHE_TTL_DAYS`, else `None`.
- `set_h1b_cache(company_key: str, company_raw: str, verified: bool) -> None`
  Upsert (INSERT OR REPLACE).

### `config.py`

```python
H1B_CACHE_TTL_DAYS = 30
```

### `prompts/screening.md`

The job JSON object gains one field:
```json
"h1b_sponsor_verified": true | false | null
```

New guidance line in the verdict section:
```
If h1b_sponsor_verified is false: add "no_h1b_history" to risk_flags and reduce confidence
by 1 (minimum 1). Do not auto-SKIP on this signal alone.
```

### `screening/stage2.py`

1. Include `h1b_sponsor_verified` in the `jobs_data` dict in `_screen_one_batch`.
2. In `_default_apply` and `_default_maybe`, inject `"no_h1b_history"` into `risk_flags` when
   `job.h1b_sponsor_verified is False`, so unverified companies are flagged even when the
   Claude CLI batch errors out.

### `main.py`

- Bump `TOTAL_PHASES` from 9 to 10.
- Insert Phase 7 block after Stage 1 and before SQLite persist.
- Import `H1BChecker` from `screening.h1b_checker`.
- Phase 7 log line: `"<N> companies checked · <V> verified · <U> unverified · <S> skipped (curated)"`

## Data Flow

```
passed_jobs (RawJob list, post-Stage-1)
  → H1BChecker.check_batch()
      → for each open-source job:
          normalize company name
          → cache hit?  use cached verified
          → cache miss? scrape h1bdata.info → cache result
          mutate job.h1b_sponsor_verified
  → jobs now carry h1b_sponsor_verified
  → Stage 2 receives field in job JSON
  → Claude sets risk_flags / adjusts confidence
  → ScreenedJob.risk_flags may contain "no_h1b_history"
  → Written to Daily tab (Risk Flags column)
```

## Error Handling & Graceful Degradation

| Scenario | Behaviour |
|---|---|
| h1bdata.info timeout | `h1b_sponsor_verified = None` — no flag, no penalty |
| h1bdata.info HTTP error | Same as timeout |
| HTML parse failure | Same as timeout |
| Cache DB error | Log warning, fall through to live scrape |
| Stage 2 Claude batch fails | `_default_apply`/`_default_maybe` injects flag from field directly |

The feature degrades silently — a broken h1bdata.info means jobs pass through unflagged,
not that the pipeline errors out.

## Out of Scope

- Downloading or hosting DOL LCA data locally (future optimisation if h1bdata.info becomes unreliable).
- Hard-rejecting companies with no H1B history (user chose soft downgrade).
- Any UI changes to the Sheets columns (risk_flags already has a column in the Daily tab).

## Notes

- Workday companies are **not exempt** — all Workday jobs are checked regardless of whether
  the company appears in `target_companies.yaml`. Only Greenhouse, Lever, and Ashby sources
  are trusted without a lookup.
