"""
============================================================
  INTELLIGENT JOB SEARCH CONFIG
  Edit this file to change search preferences and thresholds.
  Secrets live in .env — not here.
============================================================
"""

import os
import shutil
from dotenv import load_dotenv

load_dotenv()

# ── PERSONAL INFO ──────────────────────────────────────────
YOUR_NAME = os.getenv("YOUR_NAME", "Yashwanth Medisetti")
YOUR_EMAIL = os.getenv("YOUR_EMAIL", "yashwanthsaikrishna@gmail.com")
YOUR_PHONE = os.getenv("YOUR_PHONE", "+1 (630) 276 8408")

# ── GOOGLE INTEGRATIONS ───────────────────────────────────
GOOGLE_SHEETS_CREDS_FILE = os.getenv("GOOGLE_SHEETS_CREDS_FILE", "credentials.json")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Intelligent Job Search")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")

# ── DATABASE ──────────────────────────────────────────────
DB_FILE = "jobs.db"

# ── TARGET JOB TITLES ─────────────────────────────────────
# Full list used for title matching / Stage 1 filtering
TARGET_TITLES = [
    # Cloud / Infrastructure
    "Cloud Engineer",
    "Junior Cloud Engineer",
    "Associate Cloud Engineer",
    "Cloud Infrastructure Engineer",
    # DevOps / SRE / Platform
    "DevOps Engineer",
    "Junior DevOps Engineer",
    "Associate DevOps Engineer",
    "Cloud DevOps Engineer",
    "SRE",
    "Associate SRE",
    "Junior SRE",
    "Platform Engineer",
    "Associate Platform Engineer",
    # Security
    "Security Engineer",
    "Junior Security Engineer",
    "Associate Security Engineer",
    "Cloud Security Engineer",
    "DevSecOps Engineer",
    "Security Automation Engineer",
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

# ── SEARCH QUERIES ────────────────────────────────────────
# Grouped search terms for LinkedIn/Indeed — each one is a separate search.
# Keep this short: fewer broad queries > many narrow ones.
SEARCH_QUERIES = [
    "Cloud Engineer",
    "DevOps Engineer",
    "SRE Site Reliability Engineer",
    "Platform Engineer",
    "Security Engineer",
    "DevSecOps Engineer",
    "MLOps Engineer",
    "AI Infrastructure Engineer",
]

# ── LOCATIONS ─────────────────────────────────────────────
LOCATIONS = [
    "Chicago, IL",
    "New York, NY",
    "Seattle, WA",
    "Austin, TX",
    "Boston, MA",
    "Denver, CO",
    "Philadelphia, PA",
    "Washington, DC",
    "Remote",
]

# ── CLAUDE CLI ────────────────────────────────────────────
# Auto-detect Claude CLI path. Falls back to common install locations.
CLAUDE_CLI = (
    shutil.which("claude")
    or os.path.expanduser("~/.local/bin/claude.exe")
    or os.path.expanduser("~/.local/bin/claude")
    or "claude"
)

# ── SCRAPER SETTINGS ──────────────────────────────────────
RESULTS_PER_SEARCH = 20
HOURS_OLD = 24
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
    "aws", "cloud", "kubernetes", "k8s", "terraform", "devops",
    "security", "iam", "sre", "platform", "infrastructure",
    "ci/cd", "docker", "jenkins", "github actions", "ansible",
    "mlops", "ai", "machine learning", "ml pipeline",
]

# ── SALARY FLOOR ──────────────────────────────────────────
SALARY_FLOOR = 80_000

# ── SCREENING SETTINGS ────────────────────────────────────
SCREENING_CONFIDENCE_THRESHOLD = 3  # Minimum confidence for APPLY verdict
SCREENING_BATCH_SIZE = 10           # JDs per Claude CLI invocation

# ── DAILY TAB COLUMNS ─────────────────────────────────────
DAILY_HEADERS = [
    "Date Scraped", "Company", "Job Title", "Location", "Source",
    "Confidence", "AI Reasoning", "Suggested Angle", "Risk Flags",
    "Match Signals", "Salary Range", "Apply Link", "Status", "Notes",
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
