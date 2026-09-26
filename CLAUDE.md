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

# Resume project scorer: rebuild skill rarity table (monthly), replay over past
# applications, and per-project usage/callbacks for the tracker
python scripts/build_skill_idf.py
python scripts/replay_project_scorer.py
python scripts/project_usage.py

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

## Portfolio projects (set 2026-09-26)

- docs/projects/*.md are 15 portfolio project specs; profile.yaml
  `portfolio_catalog:` points at them, `projects:` holds built projects. Both
  carry skill tags from generation/skill_taxonomy.py (spec front matter /
  `skills:` block).
- generation/project_scorer.py picks the resume's 3 projects per JD
  deterministically (rarity x section x repetition x title boost, greedy
  diversity). ResumeEngine strips `projects`/`portfolio_catalog` from the
  cached system prompt and sends only the 3 picks in the per-job slice.
- The generator may select ANY catalog project regardless of build status
  (user decision). Status lives only in the Portfolio Build Board artifact
  (https://claude.ai/artifact/UwPKd8R8zVisEQnc44H9Mp, db collection `projects`,
  usage in `stats/usage`). Portfolio-project bullets may only use the spec's
  target metrics.
- Stage 2 sees a one-line-per-project catalog and may raise confidence by at
  most 1 for skill gaps a catalog project covers (prompts/screening.md rule 3).
- feedback rows record projects_used, project_coverage and admission
  (core | it_identity); the Applied tab Notes column lists the projects.

## Targeting strategy (set 2026-09-13)

Retargeted to infrastructure only, from outcome data in the "Seven Callbacks"
audit: 1,003 applications produced 7 callbacks, ALL of them infrastructure roles
(Cloud 4.35%, SRE 2.20%, Systems/Infra 1.41%) while AI/ML (0/238), Software
Engineer (0/128) and Security Analyst (0/73) produced none.

- TARGET_TITLES is infra titles plus AI engineering (MLOps, AI Engineer,
  Generative AI Engineer, Machine Learning Engineer). AI was restored 2026-09-16
  at the user's call: the infra-only gate dropped an LLMOps "AI Engineer" role
  (NYU Langone) that sent an assessment. Do not narrow AI back out without asking.
- TITLE_DOMAIN_KEYWORDS includes the AI/ML words (ai, genai, llm, ml, ...) but
  not bare "security"; security titles must also carry an infra word
- IT/identity titles (sysadmin, Windows, identity/IAM, endpoint, M365, VMware)
  were opened 2026-09-26 via IT_IDENTITY_TITLE_KEYWORDS, backed by the
  docs/projects portfolio catalog. They pass only without a security word:
  the user chose to keep Security Engineer / analyst titles out.
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
