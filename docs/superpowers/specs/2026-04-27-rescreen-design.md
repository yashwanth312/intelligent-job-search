# rescreen.py — Design Spec

**Date:** 2026-04-27

## Goal

A standalone script that re-runs Stage 2 Claude CLI screening on all jobs currently in the Daily tab and rewrites the sheet with updated verdicts, confidence scores, and reasoning. Useful after changing the screening prompt, profile, or config without re-running the full scrape pipeline.

## Approach

Option A: Read sheet → SQLite description lookup → Stage 2 rescreen → clear-and-rewrite.

## Flow

1. **Init** — open `SheetsClient`, open `Database` (read-only queries only)
2. **Read Daily tab** — `ws.get_all_records()` returns all current rows as dicts
3. **Reconstruct RawJobs** — for each row:
   - Derive fingerprint: `company.strip().lower() + "||" + title.strip().lower()`
   - Look up full job record from SQLite via `db.get_job_by_fingerprint(fingerprint)`
   - If found with a description → build `RawJob` from DB columns
   - If not found or description is empty → build `RawJob` from sheet columns with `description=None`
4. **Stage 2 screen** — `Stage2Screen(profile_path="profile.yaml").screen_batch(raw_jobs)`
5. **Rewrite Daily tab** — `daily_ops.clear_and_write_headers(ws)` + `daily_ops.write_screened_jobs(ws, screened_jobs)`
6. **Print summary** — APPLY / MAYBE / SKIP counts to stdout

## Data Reconstruction Notes

- **Salary**: sheet stores `"$80,000 - $120,000"` string — reconstructed `RawJob` will have `salary_min=None, salary_max=None`. The rewrite will show an empty Salary Range column.
- **Posted**: sheet stores `"3h ago"` — reconstructed `RawJob` will have `posted_at=None`. The rewrite will show an empty Posted column.
- Both are cosmetic losses acceptable for a rescreen run.

## What is NOT updated

- **Audit tab** — the Audit tab tracks scrape-run pipeline history, not manual rescreens.
- **SQLite screening_audit table** — same reason; rescreen results are not persisted to DB.

## Files Touched

- `rescreen.py` — new file at project root (only file created)

## Dependencies

Reuses existing modules with no changes:
- `sheets/client.py` → `SheetsClient`
- `sheets/daily.py` → `clear_and_write_headers`, `write_screened_jobs`
- `db/database.py` → `Database`
- `screening/stage2.py` → `Stage2Screen`
- `models/job.py` → `RawJob`
- `config.py` → `DB_FILE`, `SCREENING_BATCH_SIZE`
