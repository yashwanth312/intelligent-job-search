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
YOUR_NAME = os.getenv("YOUR_NAME", "Yashwanth Medisetti")
YOUR_EMAIL = os.getenv("YOUR_EMAIL", "yashwanthsaikrishna@gmail.com")
YOUR_PHONE = os.getenv("YOUR_PHONE", "(630) 276 8408")
YOUR_LOCATION_FALLBACK = os.getenv("YOUR_LOCATION_FALLBACK", "Chicago, IL")
YOUR_LINKEDIN = os.getenv("YOUR_LINKEDIN", "linkedin.com/in/yashwanth-medisetti")
YOUR_GITHUB = os.getenv("YOUR_GITHUB", "github.com/yashwanth312")

# ── GOOGLE INTEGRATIONS ───────────────────────────────────
GOOGLE_SHEETS_CREDS_FILE = os.getenv("GOOGLE_SHEETS_CREDS_FILE", "credentials.json")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Intelligent Job Search")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")

# ── DATABASE ──────────────────────────────────────────────
DB_FILE = "jobs.db"

# ── TARGET JOB TITLES ─────────────────────────────────────
# Used as both LinkedIn/Indeed search queries AND Stage 1 title matching.
# Each title gets its own dedicated search so niche titles are never buried.
TARGET_TITLES = [
    # Cloud / Infrastructure
    "Cloud Engineer",
    "Junior Cloud Engineer",
    "Associate Cloud Engineer",
    "Cloud Infrastructure Engineer",
    "Infrastructure Engineer",
    "Systems Engineer",
    # DevOps / SRE / Platform
    "DevOps Engineer",
    "Junior DevOps Engineer",
    "Associate DevOps Engineer",
    "Cloud DevOps Engineer",
    "SRE",
    "Site Reliability Engineer",
    "Associate SRE",
    "Junior SRE",
    "Reliability Engineer",
    "Platform Engineer",
    "Associate Platform Engineer",
    "Kubernetes Engineer",
    "Observability Engineer",
    # Security
    "Security Engineer",
    "Junior Security Engineer",
    "Associate Security Engineer",
    "Cloud Security Engineer",
    "DevSecOps Engineer",
    "Security Automation Engineer",
    "Security Operations Engineer",
    "Security Analyst",
    "Junior Security Analyst",
    # AI Intersection
    "MLOps Engineer",
    "AI Infrastructure Engineer",
    "AI Platform Engineer",
    "AI Security Engineer",
    "ML Platform Engineer",
    "AI DevOps Engineer",
]

# ── LOCATIONS ─────────────────────────────────────────────
# Cast the widest net across US tech hubs. 24h freshness filter
# keeps volume sane even with 17 locations.
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
]

# ── SALARY FLOOR ──────────────────────────────────────────
SALARY_FLOOR = 80_000

# ── SCREENING SETTINGS ────────────────────────────────────
SCREENING_CONFIDENCE_THRESHOLD = 3  # Minimum confidence for APPLY verdict
SCREENING_BATCH_SIZE = 5            # JDs per Claude CLI invocation (Windows argv limit ~32KB; 10 overflows with 3KB descs)
H1B_CACHE_TTL_DAYS = 30             # Days before re-checking a company on h1bdata.info

# ── DAILY TAB COLUMNS ─────────────────────────────────────
# Status is right after Confidence so you don't have to scroll.
# Posted shows "Xh ago" — lets you pick the freshest matches at a glance.
DAILY_HEADERS = [
    "Company", "Job Title", "Location", "Confidence", "Status", "Apply Link",
    "Posted", "Source", "AI Reasoning", "Suggested Angle", "Match Signals",
    "Risk Flags", "Salary Range", "Notes",
]

# ── AUDIT TAB COLUMNS ─────────────────────────────────────
AUDIT_HEADERS = [
    "Company", "Job Title", "Killed At", "Reason", "Source", "Apply Link",
]

# ── APPLIED TAB COLUMNS ───────────────────────────────────
APPLIED_HEADERS = [
    "Date Applied", "Company", "Job Title", "Location",
    "Resume Link", "Cover Letter Link", "Apply Link",
    "Angle Used", "Screen Confidence", "Source",
    "Status", "Days Waiting", "Follow-up Date", "Follow-up Sent", "Notes",
]
