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
2. Multi-Source Scraper (sources/) — Greenhouse/Lever APIs, HN, Wellfound, BuiltIn, LinkedIn, Indeed
3. Screening Engine (screening/) — Stage 1 regex + Stage 2 Claude CLI
4. Google Sheets (sheets/) — Daily tab (ephemeral), Audit tab (ephemeral), Applied tab (persistent)
5. Resume/CL Engine (generation/) — Claude CLI + weasyprint PDFs + Google Drive
6. Feedback Loop — SQLite outcome tracking, periodic reports

## Key Patterns
- Pydantic models at all data boundaries (models/)
- Source adapters implement SourceAdapter protocol (sources/base.py)
- Prompt templates stored as files (prompts/*.md)
- All scraping is async (asyncio + aiohttp)
- Google Sheets is the ONLY user interface
- Daily + Audit tabs cleared each run; Applied tab is persistent
- All data persisted to SQLite before clearing Sheets

## Config
- config.py — all tunable parameters (titles, locations, thresholds)
- target_companies.yaml — Greenhouse/Lever/Ashby company tokens
- profile.yaml — user's profile vault (experiences, projects, skills)
- .env — secrets

## Design Spec
docs/superpowers/specs/2026-04-15-intelligent-job-search-design.md
