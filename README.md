# Intelligent Job Search

An end-to-end, AI-driven job search platform that scrapes 7+ job sources every morning, filters out noise with a two-stage screen (regex + Claude), generates tailored resumes and cover letters as PDFs, uploads them to Google Drive, and tracks every application through interview to offer in Google Sheets — all while learning from outcomes to improve future runs.

The whole system is designed to be operated from a single Google Sheet. There is no UI to build, no app to host. You run a Python command, jobs appear in the Daily tab, you mark which ones to apply to, and the system produces ready-to-submit PDFs.

---

## What it does

### 1. Scrapes 7 job sources in parallel, every day

Source adapters all implement the `SourceAdapter` protocol (`sources/base.py`) and run concurrently via `asyncio` + `aiohttp`. The orchestrator deduplicates across sources and against the SQLite history.

| Source | Type | How it works |
|---|---|---|
| **Greenhouse** | Curated company list | Direct JSON API per company token in `target_companies.yaml` |
| **Lever** | Curated company list | Direct JSON API per company token |
| **Ashby** | Curated company list | Direct JSON API per company token |
| **Workday** | Curated + auto-discovered | Tenant-specific API; descriptions back-filled only for jobs that pass title screening |
| **LinkedIn / Indeed / Google** | Keyword search | Via `python-jobspy` across all `TARGET_TITLES` × `LOCATIONS` |
| **Hacker News** | Monthly "Who is hiring" thread | Algolia search API |
| **RemoteOK** | Public feed | RemoteOK JSON feed |

Disabled / experimental adapters are also present in `sources/`: Wellfound, BuiltIn, Dice, AI-Jobs, YC startup directory.

### 2. Filters jobs through a five-phase funnel

Every run executes the 9-phase pipeline in `main.py`:

1. **Init** — load credentials, profile, SQLite, and known fingerprints from the last 5 days
2. **Clear** — wipe the Daily + Audit tabs in Google Sheets
3. **Scrape** — run all source adapters in parallel
4. **Freshness filter** — drop anything older than 24 hours (configurable)
5. **H1B sponsor check** — query [h1bdata.info](https://h1bdata.info) for each open-source job's company; drop companies with no sponsorship history (curated sources are exempt; results cached for 30 days)
6. **Stage 1 regex filter** — fast, deterministic rejection of seniority mismatches, expired clearance requirements, "no sponsorship" language, salary floor violations, and missing must-have keywords
7. **Persist** — save jobs and audit entries to SQLite (`jobs.db`)
8. **Stage 2 Claude precision screen** — invoke the local Claude CLI with profile context to produce APPLY / MAYBE / SKIP verdicts, confidence (1-5), reasoning, match signals, risk flags, and a suggested resume angle
9. **Write** — push survivors to the **Daily** tab and rejections to the **Audit** tab

### 3. Generates tailored resumes + cover letters

Run `python generate_materials.py` after picking jobs in the Daily tab. For each job marked **Apply**:

- Loads the full job description from SQLite (or fetches it from the apply URL if missing)
- Calls the Claude CLI with the job description + your `profile.yaml` and the prompt at `prompts/application_materials.md`, returning a structured JSON resume + cover letter tuned to the job's angle
- Renders both as PDFs with WeasyPrint using the HTML template at `templates/resume.html`
- Uploads them to Google Drive in a per-company / per-role folder structure (or saves locally if `GOOGLE_DRIVE_FOLDER_ID` is unset)
- Writes a row to the **Materials** tab with status, links, and the angle used
- Records the application in the `feedback` table for outcome tracking

Output layout:
```
output/
  <company-slug>/
    <YYYY-MM-DD>_<role-slug>/
      Yashwanth_Medisetti_Resume.pdf
      Yashwanth_Medisetti_Cover_Letter.pdf
      _metadata.json
```

If a PDF render fails the system writes an `.html` fallback and flags the row as `PDF Render Failed` so you can recover manually.

### 4. Tracks the full application pipeline

Three Google Sheets tabs orchestrate the workflow:

| Tab | Purpose | Lifetime |
|---|---|---|
| **Daily** | Today's screened opportunities (APPLY + MAYBE) — change Status to `Apply` to queue | Cleared every run |
| **Audit** | Why each rejected job was killed (stage, reason, source) | Cleared every run |
| **Materials** | Generated resumes/cover letters with Drive links — change Status to `Applied` after submitting | Persistent |
| **Tracker** | Live application pipeline (Applied → Phone Screen → Interview → Offer / Rejected) with follow-up dates | Persistent |

`python sync_applied.py` promotes rows from Materials (Status = `Applied`) into the Tracker tab, deduplicated by company+title fingerprint.

### 5. Closes the feedback loop

- `python feedback_sync.py` pulls outcome statuses from the Materials tab into the SQLite `feedback` table
- `python feedback_report.py` prints a calibration report showing **callback rates by source, by resume angle, and by screening confidence** so you can see which sources and angles are actually working

---

## Automations

Beyond the daily pipeline, several automations run quietly in the background:

### Workday tenant auto-discovery

While LinkedIn/Indeed are scraped, every `myworkdayjobs.com` redirect URL is parsed and the tenant captured. New tenants land in `workday_candidates.yaml` (staging only — never directly into the active scrape list). Run `python scripts/promote_workday_candidates.py` to:

1. Validate each candidate against h1bdata.info (must have sponsorship history)
2. Ping the live Workday API to confirm it returns jobs
3. Promote survivors into `target_companies.yaml`, route failures into `workday_rejected.yaml`

This keeps the active company list bounded while still continuously growing coverage.

### H1B sponsor cache

Every company sourced from open boards (LinkedIn/Indeed/Google/HN/RemoteOK) is checked against h1bdata.info on first sight. Results are cached in SQLite for 30 days. Curated sources (Greenhouse/Lever/Ashby) skip the check — you've already vetted those.

### Cross-run deduplication

A 5-day rolling window of job fingerprints is loaded at startup and used to skip already-seen postings. New runs only screen genuinely new jobs.

### Description back-fill (Workday only)

Workday's listing API doesn't return descriptions inline. Rather than fetch every Workday job (slow), only the ~50–200 that pass title-only Stage 1 get their descriptions fetched. They then re-enter the full Stage 1 + Stage 2 pipeline.

### Sheet auto-formatting

Every run re-applies header colors, conditional formatting, frozen rows, column widths, and dropdown validation across Daily / Audit / Materials / Tracker.

### Audit trail to SQLite

Every rejection at every stage (H1B, Stage 1 title, Stage 1 description, Stage 2 SKIP) is persisted to the `audit` table so you can debug *why* a job was killed days later, even after the Audit tab has been cleared.

---

## Quick start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Install the Claude CLI (required for Stage 2 + materials generation)
npm install -g @anthropic-ai/claude-code

# 3. Configure
cp .env.example .env          # fill in personal info + Drive folder ID
# place your Google service account JSON at ./credentials.json
# share the target spreadsheet with the service account email

# 4. Edit your profile vault
$EDITOR profile.yaml          # or: python update_profile.py

# 5. Run
python main.py                # daily scrape + screen
# (open the Daily tab, change Status → "Apply" for jobs you want)
python generate_materials.py  # generate tailored PDFs
# (apply, then change Status → "Applied" in the Materials tab)
python sync_applied.py        # promote applied rows into Tracker
python feedback_sync.py       # pull outcomes back to SQLite
python feedback_report.py     # see what's working
```

---

## Commands

| Command | Purpose |
|---|---|
| `python main.py` | Daily scrape + screen pipeline |
| `python generate_materials.py` | Generate resume + cover letter PDFs for "Apply" jobs |
| `python rescreen.py` | Re-run Stage 2 screening on the current Daily tab |
| `python sync_applied.py` | Promote Applied rows from Materials → Tracker |
| `python feedback_sync.py` | Sync outcomes from Materials tab → SQLite |
| `python feedback_report.py` | Source / angle / confidence calibration report |
| `python update_profile.py` | Interactive profile vault editor |
| `python scripts/promote_workday_candidates.py` | Validate + promote auto-discovered Workday tenants |
| `python scripts/verify_greenhouse_tokens.py` | Verify Greenhouse company tokens in `target_companies.yaml` |
| `python scripts/verify_lever_ashby_tokens.py` | Verify Lever + Ashby tokens |
| `python scripts/verify_workday_tokens.py` | Verify Workday tenants |
| `pytest tests/ -v` | Run the test suite |

---

## Architecture

Six components, each in its own module:

1. **Profile Vault** (`profile.yaml`) — your structured knowledge base: experiences, projects with multiple framings, skills, certifications, training. Used by both screening and generation.
2. **Multi-Source Scraper** (`sources/`) — adapter-per-source pattern, async fan-out, in-source deduplication.
3. **Screening Engine** (`screening/`) — `stage1.py` (regex), `stage2.py` (Claude CLI), `h1b_checker.py` (sponsor lookup).
4. **Google Sheets Layer** (`sheets/`) — Daily, Audit, Materials, Tracker tabs + formatting.
5. **Resume / Cover Letter Engine** (`generation/`) — Claude CLI wrapper, WeasyPrint PDF renderer, Google Drive uploader.
6. **Feedback Loop** — SQLite outcome tracking, calibration reports.

Key design patterns:

- **Pydantic models at every data boundary** (`models/`) — `RawJob`, `ScreenedJob`, `ScreeningVerdict` enum
- **Source adapters implement a single Protocol** (`sources/base.py`) — pluggable, testable
- **Prompt templates as files** (`prompts/*.md`) — version-controllable, hot-editable
- **All scraping is async** — 7 sources scraped in parallel in seconds, not minutes
- **Google Sheets is the only UI** — no web app, no React
- **Daily + Audit tabs are ephemeral** — wiped each run; SQLite is the source of truth
- **All data persisted to SQLite before sheet clearing** — nothing is lost

---

## Configuration

| File | What lives here |
|---|---|
| `config.py` | Target titles, locations, freshness window, salary floor, exclusion keywords, must-have keywords, screening thresholds, Claude CLI path detection |
| `target_companies.yaml` | Curated Greenhouse / Lever / Ashby / Workday company tokens |
| `profile.yaml` | Your experiences, projects (with multi-angle framings), skills, education, certifications |
| `.env` | Secrets — Google credentials path, Drive folder ID, personal info |
| `workday_candidates.yaml` | Auto-discovered Workday tenants awaiting validation |
| `workday_rejected.yaml` | Workday tenants that failed promotion (with reason + timestamp) |

---

## Data model

SQLite (`jobs.db`) tables:

- `jobs` — every scraped job with description, fingerprint, source, posted timestamp
- `audit` — every rejection (job_fingerprint, stage, verdict, reason, confidence, run_date)
- `feedback` — applications + outcomes (screen confidence, resume angle, applied date, outcome)
- `h1b_cache` — h1bdata.info verdicts with TTL
- `workday_candidates_seen` — discovery sightings counter

---

## Design spec

Full design rationale lives at `docs/superpowers/specs/2026-04-15-intelligent-job-search-design.md`.
