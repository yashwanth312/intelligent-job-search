# CLAUDE.md — Intelligent Job Search

## Commands

# Install dependencies
pip install -r requirements.txt

# Run daily scrape + screen pipeline
python main.py

# Generate resume + cover letter for Apply jobs
python generate_materials.py

# Sync outcomes from Applied tab to SQLite
python feedback_sync.py

# Generate feedback report
python feedback_report.py

# Update profile vault interactively
python update_profile.py

# Run tests
pytest tests/ -v

# Type check
python -m py_compile config.py main.py generate_materials.py

## Architecture

Six-component AI job search platform:
1. Profile Vault (profile.yaml) — structured YAML knowledge base
2. Multi-Source Scraper (sources/) — board APIs (Greenhouse, Lever, Ashby),
   Workday tenants, LinkedIn/Indeed/Google via JobSpy, HackerNews, RemoteOK
3. Screening Engine (screening/) — Stage 1 regex + Stage 2 Claude CLI
4. Google Sheets (sheets/) — Daily tab (ephemeral), Audit tab (ephemeral), Applied tab (persistent)
5. Resume/CL Engine (generation/) — Claude CLI + weasyprint PDFs + Google Drive
6. Feedback Loop — SQLite outcome tracking, periodic reports

## Key Patterns
- Pydantic models at all data boundaries (models/)
- Source adapters implement SourceAdapter protocol (sources/base.py)
- Prompt templates stored as files (prompts/*.md)
- All scraping is async (asyncio + aiohttp)
- Board-style ATS adapters share sources.base.scrape_boards for bounded-concurrency fan-out
- Workday and LinkedIn defer description fetches until after Stage 1's title gate
- Google Sheets is the ONLY user interface
- Daily + Audit tabs cleared each run; Applied tab is persistent
- All data persisted to SQLite before clearing Sheets

## Targeting strategy (set 2026-09-13)

Retargeted to infrastructure only, from outcome data in the "Seven Callbacks"
audit: 1,003 applications produced 7 callbacks, ALL of them infrastructure roles
(Cloud 4.35%, SRE 2.20%, Systems/Infra 1.41%) while AI/ML (0/238), Software
Engineer (0/128) and Security Analyst (0/73) produced none.

- TARGET_TITLES is infra-only; MLOps is the single AI-adjacent entry
- TITLE_DOMAIN_KEYWORDS has no bare "ai" or "security" — such titles must also
  carry an infra word, which is what the converting roles actually looked like
- Prefer direct-ATS boards over LinkedIn; grow them with
  `python scripts/discover_ats_boards.py --limit 4000 --apply`
- Workday tenants are promoted from the discovery queue on DOMAIN RELEVANCE
  (`python scripts/promote_workday_candidates.py`), not H-1B history
- H-1B matching is prefix-based against h1bdata.info and biased toward KEEP;
  see screening/h1b_checker.py and `scripts/repair_h1b_cache.py`

## Config
- config.py — all tunable parameters (titles, locations, thresholds)
- target_companies.yaml — Greenhouse/Lever/Ashby company tokens
- profile.yaml — user's profile vault (experiences, projects, skills)
- .env — secrets

## Design Spec
docs/superpowers/specs/2026-04-15-intelligent-job-search-design.md
