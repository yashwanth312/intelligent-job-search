"""
============================================================
  INTELLIGENT JOB SEARCH CONFIG
  Edit this file to change search preferences and thresholds.
  Secrets live in .env — not here.
============================================================
"""

import os
import shutil
import sys
from dotenv import load_dotenv

load_dotenv()

# ── PERSONAL INFO ──────────────────────────────────────────
# Set these in .env — see .env.example
YOUR_NAME = os.getenv("YOUR_NAME", "")
YOUR_EMAIL = os.getenv("YOUR_EMAIL", "")
YOUR_PHONE = os.getenv("YOUR_PHONE", "")
YOUR_LOCATION_FALLBACK = os.getenv("YOUR_LOCATION_FALLBACK", "")
YOUR_LINKEDIN = os.getenv("YOUR_LINKEDIN", "")
YOUR_GITHUB = os.getenv("YOUR_GITHUB", "")

# ── GOOGLE INTEGRATIONS ───────────────────────────────────
GOOGLE_SHEETS_CREDS_FILE = os.getenv("GOOGLE_SHEETS_CREDS_FILE", "credentials.json")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Intelligent Job Search")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")

# ── DATABASE ──────────────────────────────────────────────
DB_FILE = "jobs.db"

# ── TARGET JOB TITLES ─────────────────────────────────────
# Used as both LinkedIn/Indeed search queries AND Stage 1 title matching.
# Each title gets its own dedicated search so niche titles are never buried.
#
# This list deliberately excludes "Junior X" / "Associate X" variants:
# LinkedIn keyword search returns the same posting set regardless of those
# qualifiers (postings rarely put "Junior" in the title), so they were pure
# duplicate queries adding scrape time with no new postings. Seniority is
# already filtered post-scrape by EXCLUDE_TITLE_KEYWORDS below.
#
# Synonyms collapsed: SRE → "Site Reliability Engineer" (matches both),
# "Reliability Engineer" / "Observability Engineer" / "Kubernetes Engineer"
# are subsumed by SRE/Platform. "Cloud DevOps" / "AI DevOps" / "ML Platform"
# are subsumed by their broader peers.
TARGET_TITLES = [
    # Cloud / Infrastructure
    "Cloud Engineer",
    "Infrastructure Engineer",
    # DevOps / SRE / Platform
    "DevOps Engineer",
    "Site Reliability Engineer",
    "Platform Engineer",
    "DevSecOps Engineer",
    # Security
    "Security Engineer",
    "Security Analyst",
    # AI / Agentic / Automation
    "AI Engineer",
    "AI Solutions Engineer",
    "Automation Engineer",
    # AI Intersection (infra)
    "MLOps Engineer",
    "AI Platform Engineer",
]

# ── LOCATIONS ─────────────────────────────────────────────
# Cast the widest net across US tech hubs. 24h freshness filter
# keeps volume sane even with 18 locations. "United States" is a
# national catch-all on LinkedIn/Indeed that surfaces postings in
# secondary metros (Miami, Tampa, Houston, Phoenix, Charlotte, etc.)
# the city-specific queries miss; dedup absorbs the overlap.
LOCATIONS = [
    "Chicago, IL",
    "New York, NY",
    "Seattle, WA",
    "Austin, TX",
    "Boston, MA",
    "Denver, CO",
    "Philadelphia, PA",
    "Washington, DC",
    "San Francisco, CA",
    "San Jose, CA",
    "Los Angeles, CA",
    "Atlanta, GA",
    "Raleigh, NC",
    "Minneapolis, MN",
    "Dallas, TX",
    "Portland, OR",
    "United States",
    "Remote",
]

# ── CLAUDE CLI ────────────────────────────────────────────
def _find_claude_cli() -> str:
    """Locate the Claude CLI binary, trying platform-specific install paths."""
    found = shutil.which("claude")
    if found:
        return found

    if sys.platform == "win32":
        # npm installs global packages to %APPDATA%\npm on Windows.
        # This directory is often missing from PATH even though npm added it.
        appdata = os.environ.get("APPDATA", "")
        localappdata = os.environ.get("LOCALAPPDATA", "")
        for candidate in [
            os.path.join(appdata, "npm", "claude.cmd"),
            os.path.join(appdata, "npm", "claude"),
            os.path.join(localappdata, "Programs", "claude", "claude.exe"),
            os.path.join(localappdata, "AnthropicClaude", "claude.exe"),
        ]:
            if os.path.isfile(candidate):
                return candidate
    else:
        for candidate in [
            os.path.expanduser("~/.local/bin/claude"),
            os.path.expanduser("~/.npm-global/bin/claude"),
            "/usr/local/bin/claude",
        ]:
            if os.path.isfile(candidate):
                return candidate

    return "claude"  # last-resort; will fail with a clear error at runtime


CLAUDE_CLI = _find_claude_cli()

# ── SCRAPER SETTINGS ──────────────────────────────────────
# RESULTS_PER_SEARCH: per-query cap for JobSpy. With HOURS_OLD=24 the
# realistic return per (site, query, location) is often much lower,
# so a larger cap costs little and widens the net.
RESULTS_PER_SEARCH = 50
HOURS_OLD = 24  # Enforced across ALL sources via sources/orchestrator.filter_fresh_jobs
SCRAPER_WORKERS = 8
STALE_JOB_DAYS = 5

# ── TITLE EXCLUSIONS ──────────────────────────────────────
EXCLUDE_TITLE_KEYWORDS = [
    "senior", "sr.", "sr ", "lead", "staff", "principal",
    "manager", "director", "vp ", "vp,", "vice president", "head of",
    "intern", "internship", "contract", "contractor",
    "part-time", "part time", "freelance", "temporary",
]

# ── TITLE DOMAIN KEYWORDS ─────────────────────────────────
TITLE_DOMAIN_KEYWORDS = [
    "cloud", "devops", "security", "sre", "platform", "infrastructure",
    "mlops", "ai", "ml", "machine learning", "devsecops",
    "reliability", "kubernetes", "observability", "systems",
    # New role categories — Greenhouse pre-filter must capture these too
    "automation", "software", "full stack", "fullstack", "agentic",
    "llm", "generative",
]

# ── DESCRIPTION HARD-STOP PATTERNS ────────────────────────
EXCLUDE_DESC_PATTERNS = [
    "5+ years", "5 or more years", "6+ years", "7+ years",
    "8+ years", "9+ years", "10+ years",
    "five or more years", "five+ years",
    "active clearance", "security clearance required",
    "clearance required", "top secret", "ts/sci",
    "secret clearance", "dod clearance", "dod secret",
    "government clearance", "federal clearance",
    "must hold a clearance", "must have clearance",
    "no sponsorship", "cannot sponsor", "will not sponsor",
    "sponsorship is not available", "does not sponsor",
    "no visa sponsorship", "visa sponsorship not available",
    "must be a us citizen", "us citizenship required",
    "citizenship is required", "only us citizens",
    "citizens only", "must be a citizen",
]

# ── MUST-HAVE KEYWORDS ────────────────────────────────────
REQUIRE_ONE_OF = [
    "aws", "gcp", "azure", "cloud", "kubernetes", "k8s", "terraform",
    "devops", "security", "iam", "sre", "platform", "infrastructure",
    "ci/cd", "docker", "jenkins", "github actions", "ansible",
    "prometheus", "grafana", "helm", "vault", "linux", "automation",
    "mlops", "ai", "machine learning", "ml pipeline", "observability",
    # AI-native terms — AI Engineer roles may use these instead of infra keywords
    "llm", "openai", "agentic", "generative", "copilot", "rag",
    "langchain", "genai", "prompt engineering", "large language model",
    "azure openai", "gpt-4", "gpt-3", "anthropic",
]

# ── SALARY FLOOR ──────────────────────────────────────────
SALARY_FLOOR = 80_000

# ── SCREENING SETTINGS ────────────────────────────────────
SCREENING_CONFIDENCE_THRESHOLD = 3  # Minimum confidence for APPLY verdict
SCREENING_BATCH_SIZE = 5            # JDs per Claude CLI invocation (Windows argv limit ~32KB; 10 overflows with 3KB descs)
H1B_CACHE_TTL_DAYS = 30             # Days before re-checking a company on h1bdata.info

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

# ── AUDIT TAB COLUMNS ─────────────────────────────────────
AUDIT_HEADERS = [
    "Company", "Job Title", "Killed At", "Reason", "Source", "Apply Link",
]

# ── MATERIALS TAB COLUMNS ─────────────────────────────────
# Queue of generated resumes/CLs. Status: Ready to Apply → Applied → Skipped.
MATERIALS_HEADERS = [
    "Date Generated", "Company", "Job Title", "Location",
    "Resume Link", "Cover Letter Link", "Apply Link",
    "Angle Used", "Screen Confidence", "Source",
    "Status", "Notes",
]

# ── TRACKER TAB COLUMNS ───────────────────────────────────
# Pipeline for actually-applied jobs. Populated by sync_applied.py.
TRACKER_HEADERS = [
    "Date Applied", "Company", "Job Title", "Location",
    "Apply Link", "Status", "Follow-up Date", "Follow-up Sent", "Notes",
]

# Keep for any legacy references
APPLIED_HEADERS = MATERIALS_HEADERS

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
