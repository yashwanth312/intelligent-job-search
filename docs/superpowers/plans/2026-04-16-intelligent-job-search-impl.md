# Intelligent Job Search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an AI-powered job search platform that scrapes 10+ sources, screens with Claude CLI, auto-generates tailored resumes/cover letters, and tracks outcomes — all through Google Sheets as the single UI.

**Architecture:** Six components built in dependency order: Foundation (models, DB, config) → Multi-Source Scraper → Screening Engine → Sheets Integration → Main Pipeline → Resume/CL Engine → Feedback Loop. Each phase produces working, testable software.

**Tech Stack:** Python 3.10+, Pydantic v2, SQLite, aiohttp, asyncio, gspread, google-api-python-client (Drive), weasyprint, python-jobspy, Claude Code CLI (`claude -p`), PyYAML, rich (progress bars)

**Design Spec:** `docs/superpowers/specs/2026-04-15-intelligent-job-search-design.md`

**Build Strategy:**
- Use context7 MCP plugin to look up current docs before writing any library integration
- Fresh Claude CLI invocation per resume/CL pair (no context accumulation)
- Batch processing everywhere (asyncio.gather, batch_update)
- Pydantic models at all data boundaries
- Fail-fast startup validation
- Structured logging (Python `logging` module)

---

## Phase 1: Foundation

### Task 1: Project Setup

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `CLAUDE.md`

- [ ] **Step 1: Create requirements.txt**

```txt
# Core
pydantic>=2.0
pyyaml>=6.0
python-dotenv>=1.0

# Scraping
python-jobspy>=1.1
aiohttp>=3.9
beautifulsoup4>=4.12

# Google integrations
gspread>=6.0
google-api-python-client>=2.100
google-auth-httplib2>=0.2
google-auth-oauthlib>=1.2
oauth2client>=4.1

# PDF generation
weasyprint>=60.0

# CLI & UX
rich>=13.0

# Testing
pytest>=8.0
pytest-asyncio>=0.23
```

- [ ] **Step 2: Create .env.example**

```env
# Google credentials (service account JSON file path)
GOOGLE_SHEETS_CREDS_FILE=credentials.json

# Google Drive folder ID for resume/CL uploads
GOOGLE_DRIVE_FOLDER_ID=

# Spreadsheet name (created automatically if not exists)
SPREADSHEET_NAME=Intelligent Job Search

# Personal info (used in resume generation)
YOUR_NAME=Yashwanth Medisetti
YOUR_EMAIL=yashwanthsaikrishna@gmail.com
YOUR_PHONE=+1 (630) 276 8408
```

- [ ] **Step 3: Create .gitignore**

```gitignore
# Secrets
.env
credentials.json
*.json.bak

# Database
*.db

# Output
output/
logs/

# Python
__pycache__/
*.pyc
*.pyo
.venv/
venv/

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db

# Claude
.claude/
```

- [ ] **Step 4: Create CLAUDE.md**

```markdown
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
```

- [ ] **Step 5: Install dependencies and commit**

```bash
pip install -r requirements.txt
git add requirements.txt .env.example .gitignore CLAUDE.md
git commit -m "chore: project setup — requirements, gitignore, env template, CLAUDE.md"
```

---

### Task 2: Pydantic Models

**Files:**
- Create: `models/__init__.py`
- Create: `models/job.py`
- Create: `models/profile.py`
- Create: `models/materials.py`
- Create: `tests/__init__.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing tests for job models**

```python
# tests/test_models.py
import pytest
from datetime import datetime
from models.job import RawJob, ScreenedJob, ScreeningVerdict


class TestRawJob:
    def test_create_raw_job(self):
        job = RawJob(
            title="Cloud Engineer",
            company="Anthropic",
            location="San Francisco, CA",
            description="We are looking for a Cloud Engineer...",
            salary_min=120000,
            salary_max=180000,
            url="https://boards.greenhouse.io/anthropic/jobs/123",
            source="greenhouse-anthropic",
        )
        assert job.title == "Cloud Engineer"
        assert job.fingerprint == "anthropic||cloud engineer"

    def test_fingerprint_generation(self):
        job = RawJob(
            title="  DevOps Engineer ",
            company=" Google ",
            location="Remote",
            url="https://example.com",
            source="linkedin",
        )
        assert job.fingerprint == "google||devops engineer"

    def test_raw_job_optional_fields(self):
        job = RawJob(
            title="SRE",
            company="Meta",
            location="NYC",
            url="https://example.com",
            source="indeed",
        )
        assert job.description is None
        assert job.salary_min is None
        assert job.salary_max is None


class TestScreenedJob:
    def test_create_screened_job(self):
        job = ScreenedJob(
            title="AI Infrastructure Engineer",
            company="Anthropic",
            location="San Francisco, CA",
            description="...",
            url="https://example.com",
            source="greenhouse-anthropic",
            verdict=ScreeningVerdict.APPLY,
            confidence=5,
            reasoning="Strong match: AWS + K8s + ML pipeline",
            match_signals=["EKS", "Terraform", "ML pipeline"],
            risk_flags=[],
            suggested_angle="AI Infrastructure",
        )
        assert job.verdict == ScreeningVerdict.APPLY
        assert job.confidence == 5
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_models.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'models'`

- [ ] **Step 3: Implement job models**

```python
# models/__init__.py
"""Pydantic models for data validation at all boundaries."""

# models/job.py
"""Job data models — RawJob from scrapers, ScreenedJob after AI screening."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, computed_field


class ScreeningVerdict(str, Enum):
    APPLY = "APPLY"
    SKIP = "SKIP"
    MAYBE = "MAYBE"


class RawJob(BaseModel):
    """A job listing as returned by any source adapter."""

    title: str
    company: str
    location: str
    description: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    url: str
    source: str  # e.g. "greenhouse-anthropic", "hn-apr2026", "linkedin"
    scraped_at: datetime = Field(default_factory=datetime.now)

    @computed_field
    @property
    def fingerprint(self) -> str:
        return f"{self.company.strip().lower()}||{self.title.strip().lower()}"


class ScreenedJob(RawJob):
    """A job after passing through the screening engine."""

    verdict: ScreeningVerdict
    confidence: int = Field(ge=1, le=5)
    reasoning: str
    match_signals: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    suggested_angle: str = ""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_models.py -v
```
Expected: All PASS

- [ ] **Step 5: Write tests for profile models**

Add to `tests/test_models.py`:

```python
from models.profile import Profile, Experience, Project


class TestProfile:
    def test_load_profile_from_dict(self):
        data = {
            "personal": {
                "name": "Yashwanth Medisetti",
                "email": "yashwanthsaikrishna@gmail.com",
                "phone": "+1 (630) 276 8408",
                "location": "Chicago, IL",
                "visa": "F1 OPT",
            },
            "education": [],
            "experiences": [],
            "projects": [],
            "certifications": [],
            "training": [],
            "skills": {},
        }
        profile = Profile(**data)
        assert profile.personal.name == "Yashwanth Medisetti"

    def test_experience_has_raw_context(self):
        exp = Experience(
            company="KV Bits",
            location="Chicago, IL",
            period="June 2024 - Present",
            framings={"security": {"title": "Junior Security Engineer", "bullets": ["Built IAM..."]}},
            raw_context="Built infrastructure from scratch...",
        )
        assert "infrastructure" in exp.raw_context
        assert exp.framings["security"]["title"] == "Junior Security Engineer"
```

- [ ] **Step 6: Implement profile models**

```python
# models/profile.py
"""Profile vault models — structured representation of the user's experience."""
from __future__ import annotations

from pydantic import BaseModel


class PersonalInfo(BaseModel):
    name: str
    email: str
    phone: str
    location: str
    visa: str
    linkedin: str = ""


class Education(BaseModel):
    school: str
    degree: str
    gpa: str
    graduation: str


class Framing(BaseModel):
    title: str = ""
    bullets: list[str] = []


class Experience(BaseModel):
    company: str
    location: str
    period: str
    framings: dict[str, dict]  # e.g. {"security": {"title": "...", "bullets": [...]}}
    raw_context: str = ""


class Project(BaseModel):
    name: str
    raw_context: str = ""
    framings: dict[str, dict] = {}  # e.g. {"healthcare": {"bullets": [...]}}


class Certification(BaseModel):
    name: str
    issuer: str = ""
    status: str = ""
    expires: str = ""
    note: str = ""


class Profile(BaseModel):
    personal: PersonalInfo
    education: list[Education] = []
    experiences: list[Experience] = []
    projects: list[Project] = []
    certifications: list[Certification] = []
    training: list[str] = []
    skills: dict[str, list[str]] = {}
```

- [ ] **Step 7: Implement materials model**

```python
# models/materials.py
"""Generated resume/cover letter metadata model."""
from __future__ import annotations

from pydantic import BaseModel


class ResumeDecisions(BaseModel):
    angle: str
    kvbits_framing: str = ""
    ti_framing: str = ""
    projects_included: list[str] = []
    projects_excluded: dict[str, str] = {}  # project_name -> reason
    skills_reordered: str = ""
    certs_highlighted: list[str] = []


class GeneratedMaterials(BaseModel):
    job_fingerprint: str
    company: str
    title: str
    resume_content: dict  # structured resume sections
    cover_letter: str
    decisions: ResumeDecisions
    resume_drive_url: str = ""
    cover_letter_drive_url: str = ""
```

- [ ] **Step 8: Run all tests and commit**

```bash
pytest tests/test_models.py -v
git add models/ tests/
git commit -m "feat: add Pydantic models for jobs, profile vault, and generated materials"
```

---

### Task 3: SQLite Database

**Files:**
- Create: `db/__init__.py`
- Create: `db/database.py`
- Create: `db/queries.py`
- Create: `tests/test_database.py`

- [ ] **Step 1: Write failing tests for database**

```python
# tests/test_database.py
import os
import pytest
from db.database import Database
from models.job import RawJob, ScreenedJob, ScreeningVerdict


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    database.initialize()
    yield database
    database.close()


class TestDatabase:
    def test_initialize_creates_tables(self, db):
        tables = db.get_tables()
        assert "jobs" in tables
        assert "screening_audit" in tables
        assert "feedback" in tables

    def test_save_and_retrieve_job(self, db):
        job = RawJob(
            title="Cloud Engineer",
            company="Google",
            location="Remote",
            description="A cloud role",
            url="https://example.com",
            source="greenhouse-google",
        )
        db.save_jobs([job])
        retrieved = db.get_job_by_fingerprint("google||cloud engineer")
        assert retrieved is not None
        assert retrieved["title"] == "Cloud Engineer"

    def test_fingerprint_exists(self, db):
        job = RawJob(
            title="SRE", company="Meta", location="NYC",
            url="https://example.com", source="linkedin",
        )
        db.save_jobs([job])
        assert db.fingerprint_exists("meta||sre") is True
        assert db.fingerprint_exists("meta||devops") is False

    def test_save_screening_audit(self, db):
        db.save_audit_entry(
            job_fingerprint="google||cloud engineer",
            company="Google",
            title="Cloud Engineer",
            source="greenhouse-google",
            stage="stage1_title",
            verdict="REJECT",
            reason="title contains 'senior'",
            run_date="2026-04-16",
        )
        audits = db.get_audit_entries("2026-04-16")
        assert len(audits) == 1
        assert audits[0]["reason"] == "title contains 'senior'"

    def test_save_feedback(self, db):
        db.save_feedback(
            job_fingerprint="google||cloud engineer",
            company="Google",
            title="Cloud Engineer",
            source="greenhouse-google",
            screen_confidence=4,
            resume_angle="AI Infrastructure",
            date_applied="2026-04-16",
        )
        fb = db.get_all_feedback()
        assert len(fb) == 1
        assert fb[0]["resume_angle"] == "AI Infrastructure"

    def test_bulk_fingerprint_check(self, db):
        jobs = [
            RawJob(title="SRE", company="Meta", location="NYC",
                   url="https://a.com", source="linkedin"),
            RawJob(title="DevOps", company="Google", location="SF",
                   url="https://b.com", source="indeed"),
        ]
        db.save_jobs(jobs)
        known = db.get_known_fingerprints({"meta||sre", "google||devops", "unknown||job"})
        assert "meta||sre" in known
        assert "google||devops" in known
        assert "unknown||job" not in known
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_database.py -v
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement database module**

```python
# db/__init__.py
"""SQLite database for job storage, audit trails, and feedback."""

# db/database.py
"""SQLite database connection and operations."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from models.job import RawJob


class Database:
    def __init__(self, db_path: str = "jobs.db"):
        self.db_path = db_path
        self.conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def _create_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT,
                description TEXT,
                salary_min INTEGER,
                salary_max INTEGER,
                url TEXT,
                source TEXT,
                scraped_at TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS screening_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_fingerprint TEXT NOT NULL,
                company TEXT,
                title TEXT,
                source TEXT,
                stage TEXT NOT NULL,
                verdict TEXT NOT NULL,
                reason TEXT,
                confidence INTEGER,
                run_date TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_fingerprint TEXT NOT NULL,
                company TEXT,
                title TEXT,
                source TEXT,
                screen_confidence INTEGER,
                resume_angle TEXT,
                date_applied TEXT,
                outcome TEXT DEFAULT 'applied',
                days_to_response INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint);
            CREATE INDEX IF NOT EXISTS idx_audit_run_date ON screening_audit(run_date);
            CREATE INDEX IF NOT EXISTS idx_feedback_fingerprint ON feedback(job_fingerprint);
        """)

    def get_tables(self) -> list[str]:
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        return [row["name"] for row in cursor.fetchall()]

    def save_jobs(self, jobs: list[RawJob]) -> int:
        saved = 0
        for job in jobs:
            try:
                self.conn.execute(
                    """INSERT OR IGNORE INTO jobs
                    (fingerprint, title, company, location, description,
                     salary_min, salary_max, url, source, scraped_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        job.fingerprint, job.title, job.company, job.location,
                        job.description, job.salary_min, job.salary_max,
                        job.url, job.source, job.scraped_at.isoformat(),
                    ),
                )
                saved += 1
            except sqlite3.IntegrityError:
                pass
        self.conn.commit()
        return saved

    def get_job_by_fingerprint(self, fingerprint: str) -> dict | None:
        cursor = self.conn.execute(
            "SELECT * FROM jobs WHERE fingerprint = ?", (fingerprint,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def fingerprint_exists(self, fingerprint: str) -> bool:
        cursor = self.conn.execute(
            "SELECT 1 FROM jobs WHERE fingerprint = ?", (fingerprint,)
        )
        return cursor.fetchone() is not None

    def get_known_fingerprints(self, fingerprints: set[str]) -> set[str]:
        if not fingerprints:
            return set()
        placeholders = ",".join("?" for _ in fingerprints)
        cursor = self.conn.execute(
            f"SELECT fingerprint FROM jobs WHERE fingerprint IN ({placeholders})",
            list(fingerprints),
        )
        return {row["fingerprint"] for row in cursor.fetchall()}

    def save_audit_entry(
        self, job_fingerprint: str, company: str, title: str,
        source: str, stage: str, verdict: str, reason: str,
        run_date: str, confidence: int | None = None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO screening_audit
            (job_fingerprint, company, title, source, stage, verdict, reason, confidence, run_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_fingerprint, company, title, source, stage, verdict, reason, confidence, run_date),
        )
        self.conn.commit()

    def save_audit_entries_bulk(self, entries: list[dict]) -> None:
        self.conn.executemany(
            """INSERT INTO screening_audit
            (job_fingerprint, company, title, source, stage, verdict, reason, confidence, run_date)
            VALUES (:job_fingerprint, :company, :title, :source, :stage, :verdict, :reason, :confidence, :run_date)""",
            entries,
        )
        self.conn.commit()

    def get_audit_entries(self, run_date: str) -> list[dict]:
        cursor = self.conn.execute(
            "SELECT * FROM screening_audit WHERE run_date = ?", (run_date,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def save_feedback(
        self, job_fingerprint: str, company: str, title: str,
        source: str, screen_confidence: int, resume_angle: str,
        date_applied: str,
    ) -> None:
        self.conn.execute(
            """INSERT INTO feedback
            (job_fingerprint, company, title, source, screen_confidence, resume_angle, date_applied)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (job_fingerprint, company, title, source, screen_confidence, resume_angle, date_applied),
        )
        self.conn.commit()

    def update_feedback_outcome(self, job_fingerprint: str, outcome: str) -> None:
        self.conn.execute(
            """UPDATE feedback SET outcome = ?, updated_at = datetime('now')
            WHERE job_fingerprint = ?""",
            (outcome, job_fingerprint),
        )
        self.conn.commit()

    def get_all_feedback(self) -> list[dict]:
        cursor = self.conn.execute("SELECT * FROM feedback ORDER BY date_applied DESC")
        return [dict(row) for row in cursor.fetchall()]

    def get_description_by_fingerprint(self, fingerprint: str) -> str | None:
        cursor = self.conn.execute(
            "SELECT description FROM jobs WHERE fingerprint = ?", (fingerprint,)
        )
        row = cursor.fetchone()
        return row["description"] if row else None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_database.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add db/ tests/test_database.py
git commit -m "feat: add SQLite database with jobs, screening_audit, and feedback tables"
```

---

### Task 4: Config Module

**Files:**
- Create: `config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_config.py
import pytest
from config import (
    TARGET_TITLES, LOCATIONS, EXCLUDE_TITLE_KEYWORDS,
    SALARY_FLOOR, SCREENING_CONFIDENCE_THRESHOLD,
    TITLE_DOMAIN_KEYWORDS, SCREENING_BATCH_SIZE,
)


class TestConfig:
    def test_target_titles_include_ai_roles(self):
        titles_lower = [t.lower() for t in TARGET_TITLES]
        assert any("mlops" in t for t in titles_lower)
        assert any("ai" in t for t in titles_lower)

    def test_target_titles_include_cloud_roles(self):
        titles_lower = [t.lower() for t in TARGET_TITLES]
        assert any("cloud" in t for t in titles_lower)
        assert any("devops" in t for t in titles_lower)

    def test_locations_include_remote(self):
        assert "Remote" in LOCATIONS

    def test_salary_floor(self):
        assert SALARY_FLOOR >= 70000

    def test_screening_defaults(self):
        assert SCREENING_CONFIDENCE_THRESHOLD >= 1
        assert SCREENING_BATCH_SIZE >= 1
```

- [ ] **Step 2: Implement config.py**

```python
# config.py
"""
============================================================
  INTELLIGENT JOB SEARCH CONFIG
  Edit this file to change search preferences and thresholds.
  Secrets live in .env — not here.
============================================================
"""

import os
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
SALARY_FLOOR = 70_000

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
```

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/test_config.py -v
git add config.py tests/test_config.py
git commit -m "feat: add config module with titles, locations, filters, and column definitions"
```

---

### Task 5: Profile Vault

**Files:**
- Create: `profile.yaml`
- Create: `target_companies.yaml`
- Create: `tests/test_profile_loader.py`

- [ ] **Step 1: Write failing test for profile loading**

```python
# tests/test_profile_loader.py
import pytest
import yaml
from pathlib import Path
from models.profile import Profile


class TestProfileLoader:
    def test_load_profile_yaml(self, tmp_path):
        profile_data = {
            "personal": {
                "name": "Test User",
                "email": "test@test.com",
                "phone": "123",
                "location": "NYC",
                "visa": "F1 OPT",
            },
            "education": [{"school": "MIT", "degree": "MS CS", "gpa": "4.0", "graduation": "2025"}],
            "experiences": [{
                "company": "TestCo",
                "location": "NYC",
                "period": "2024-present",
                "framings": {"devops": {"title": "DevOps Eng", "bullets": ["Did stuff"]}},
                "raw_context": "Built infra from scratch",
            }],
            "projects": [{"name": "TestProject", "raw_context": "A test project"}],
            "certifications": [{"name": "Security+", "issuer": "CompTIA", "status": "Active"}],
            "training": ["Docker", "K8s"],
            "skills": {"cloud": ["AWS", "GCP"]},
        }
        path = tmp_path / "profile.yaml"
        path.write_text(yaml.dump(profile_data, default_flow_style=False))

        with open(path) as f:
            data = yaml.safe_load(f)
        profile = Profile(**data)
        assert profile.personal.name == "Test User"
        assert len(profile.experiences) == 1
        assert profile.experiences[0].company == "TestCo"
```

- [ ] **Step 2: Run test to verify it passes** (model already exists)

```bash
pytest tests/test_profile_loader.py -v
```
Expected: PASS (Profile model was implemented in Task 2)

- [ ] **Step 3: Create profile.yaml**

Copy the full profile vault from the design spec (Section: Component 1: Profile Vault). The file is too long to inline here — it's the complete YAML starting with `personal:` through `skills:` from the spec. The spec contains the authoritative content.

- [ ] **Step 4: Create target_companies.yaml**

```yaml
# target_companies.yaml
# Greenhouse/Lever/Ashby company board tokens for direct API scraping.
# Add/remove companies as needed. Token is the URL slug used in the API.

greenhouse:
  # AI companies
  - token: anthropic
    name: Anthropic
  - token: openai
    name: OpenAI
  - token: huggingface
    name: Hugging Face
  - token: scale
    name: Scale AI
  - token: cohere
    name: Cohere
  - token: databricks
    name: Databricks
  - token: anyscale
    name: Anyscale

  # Cloud / Infrastructure
  - token: cloudflare
    name: Cloudflare
  - token: datadog
    name: Datadog
  - token: hashicorp
    name: HashiCorp
  - token: elastic
    name: Elastic
  - token: grafanalabs
    name: Grafana Labs
  - token: confluent
    name: Confluent

  # Security
  - token: crowdstrike
    name: CrowdStrike
  - token: paloaltonetworks
    name: Palo Alto Networks
  - token: snyk
    name: Snyk
  - token: lacework
    name: Lacework
  - token: sentinelone
    name: SentinelOne

  # Big Tech
  - token: stripe
    name: Stripe
  - token: figma
    name: Figma
  - token: notion
    name: Notion
  - token: discord
    name: Discord
  - token: reddit
    name: Reddit
  - token: airbnb
    name: Airbnb
  - token: doordash
    name: DoorDash
  - token: lyft
    name: Lyft
  - token: plaid
    name: Plaid
  - token: brex
    name: Brex
  - token: ramp
    name: Ramp

lever:
  # Add Lever companies as discovered
  []

ashby:
  # Add Ashby companies as discovered
  []
```

- [ ] **Step 5: Commit**

```bash
git add profile.yaml target_companies.yaml tests/test_profile_loader.py
git commit -m "feat: add profile vault, target companies list, and profile loader test"
```

---

## Phase 2: Multi-Source Scraper

### Task 6: Source Adapter Base

**Files:**
- Create: `sources/__init__.py`
- Create: `sources/base.py`
- Create: `tests/test_sources.py`

- [ ] **Step 1: Write test for adapter interface**

```python
# tests/test_sources.py
import pytest
from sources.base import SourceAdapter, SourceResult
from models.job import RawJob


class MockAdapter(SourceAdapter):
    name = "mock"

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        jobs = [
            RawJob(
                title="Cloud Engineer", company="TestCo", location="Remote",
                description="A cloud job", url="https://test.com/1", source="mock",
            )
        ]
        return SourceResult(jobs=jobs, errors=[])


class TestSourceAdapter:
    @pytest.mark.asyncio
    async def test_mock_adapter_returns_jobs(self):
        adapter = MockAdapter()
        result = await adapter.scrape(["Cloud Engineer"], ["Remote"])
        assert len(result.jobs) == 1
        assert result.jobs[0].source == "mock"
        assert len(result.errors) == 0

    def test_adapter_has_name(self):
        adapter = MockAdapter()
        assert adapter.name == "mock"
```

- [ ] **Step 2: Implement base adapter**

```python
# sources/__init__.py
"""Pluggable job source adapters."""

# sources/base.py
"""Base interface for all source adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from models.job import RawJob


@dataclass
class SourceResult:
    jobs: list[RawJob] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class SourceAdapter(ABC):
    name: str = "base"

    @abstractmethod
    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        ...
```

- [ ] **Step 3: Run test and commit**

```bash
pytest tests/test_sources.py -v
git add sources/__init__.py sources/base.py tests/test_sources.py
git commit -m "feat: add SourceAdapter base interface and SourceResult model"
```

---

### Task 7: Greenhouse Adapter

**Files:**
- Create: `sources/greenhouse.py`
- Create: `tests/test_greenhouse.py`

**Before writing:** Use context7 to look up the Greenhouse Job Board API docs. The public endpoint is `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true` — no auth required, returns JSON with job objects containing `title`, `location.name`, `content` (HTML description), `absolute_url`, `updated_at`, and optionally pay transparency data with `?pay_transparency=true`.

- [ ] **Step 1: Write failing test with mocked HTTP**

```python
# tests/test_greenhouse.py
import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from sources.greenhouse import GreenhouseAdapter


MOCK_GREENHOUSE_RESPONSE = {
    "jobs": [
        {
            "id": 123,
            "title": "Cloud Engineer",
            "location": {"name": "San Francisco, CA"},
            "content": "<p>We need a Cloud Engineer with AWS experience.</p>",
            "absolute_url": "https://boards.greenhouse.io/testco/jobs/123",
            "updated_at": "2026-04-15T10:00:00Z",
            "metadata": [],
        },
        {
            "id": 456,
            "title": "Senior Staff Engineer",
            "location": {"name": "Remote"},
            "content": "<p>10+ years experience required.</p>",
            "absolute_url": "https://boards.greenhouse.io/testco/jobs/456",
            "updated_at": "2026-04-15T10:00:00Z",
            "metadata": [],
        },
    ]
}


class TestGreenhouseAdapter:
    @pytest.mark.asyncio
    async def test_scrape_returns_jobs(self):
        adapter = GreenhouseAdapter(
            companies=[{"token": "testco", "name": "TestCo"}]
        )

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=MOCK_GREENHOUSE_RESPONSE)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncContextManager(mock_response))

        result = await adapter._scrape_company(mock_session, "testco", "TestCo")
        assert len(result) == 2
        assert result[0].company == "TestCo"
        assert result[0].source == "greenhouse-testco"
        assert "Cloud Engineer" in [j.title for j in result]

    @pytest.mark.asyncio
    async def test_handles_404_gracefully(self):
        adapter = GreenhouseAdapter(
            companies=[{"token": "nonexistent", "name": "Gone"}]
        )

        mock_response = AsyncMock()
        mock_response.status = 404

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncContextManager(mock_response))

        result = await adapter._scrape_company(mock_session, "nonexistent", "Gone")
        assert len(result) == 0


class AsyncContextManager:
    """Helper to mock async context managers."""
    def __init__(self, return_value):
        self.return_value = return_value
    async def __aenter__(self):
        return self.return_value
    async def __aexit__(self, *args):
        pass
```

- [ ] **Step 2: Implement Greenhouse adapter**

```python
# sources/greenhouse.py
"""Greenhouse Job Board API adapter — no auth required."""
from __future__ import annotations

import logging
from datetime import datetime

import aiohttp
from bs4 import BeautifulSoup

from models.job import RawJob
from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseAdapter(SourceAdapter):
    name = "greenhouse"

    def __init__(self, companies: list[dict]):
        """companies: list of {"token": "anthropic", "name": "Anthropic"}"""
        self.companies = companies

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        jobs: list[RawJob] = []
        errors: list[str] = []

        async with aiohttp.ClientSession() as session:
            for company in self.companies:
                try:
                    company_jobs = await self._scrape_company(
                        session, company["token"], company["name"]
                    )
                    jobs.extend(company_jobs)
                except Exception as e:
                    msg = f"Greenhouse {company['name']}: {e}"
                    logger.warning(msg)
                    errors.append(msg)

        logger.info(f"Greenhouse: scraped {len(jobs)} jobs from {len(self.companies)} companies")
        return SourceResult(jobs=jobs, errors=errors)

    async def _scrape_company(
        self, session: aiohttp.ClientSession, token: str, name: str
    ) -> list[RawJob]:
        url = f"{GREENHOUSE_API}/{token}/jobs?content=true"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                logger.warning(f"Greenhouse {name}: HTTP {resp.status}")
                return []
            data = await resp.json()

        jobs: list[RawJob] = []
        for item in data.get("jobs", []):
            description_html = item.get("content", "")
            description = BeautifulSoup(description_html, "html.parser").get_text(
                separator="\n", strip=True
            ) if description_html else None

            location_name = ""
            loc = item.get("location")
            if isinstance(loc, dict):
                location_name = loc.get("name", "")
            elif isinstance(loc, str):
                location_name = loc

            jobs.append(
                RawJob(
                    title=item.get("title", ""),
                    company=name,
                    location=location_name,
                    description=description,
                    url=item.get("absolute_url", ""),
                    source=f"greenhouse-{token}",
                )
            )

        return jobs
```

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/test_greenhouse.py -v
git add sources/greenhouse.py tests/test_greenhouse.py
git commit -m "feat: add Greenhouse Job Board API adapter"
```

---

### Task 8: Lever Adapter

**Files:**
- Create: `sources/lever.py`
- Create: `tests/test_lever.py`

**Lever API:** `GET https://api.lever.co/v0/postings/{company}` — no auth, returns JSON array of postings with `text` (title), `categories.location`, `descriptionPlain`, `hostedUrl`, `createdAt`.

- [ ] **Step 1: Write failing test with mocked HTTP**

```python
# tests/test_lever.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from sources.lever import LeverAdapter
from tests.test_greenhouse import AsyncContextManager


MOCK_LEVER_RESPONSE = [
    {
        "id": "abc123",
        "text": "DevOps Engineer",
        "categories": {"location": "New York, NY", "team": "Infrastructure"},
        "descriptionPlain": "We need a DevOps engineer with K8s experience.",
        "hostedUrl": "https://jobs.lever.co/testco/abc123",
        "createdAt": 1713200000000,
    },
]


class TestLeverAdapter:
    @pytest.mark.asyncio
    async def test_scrape_returns_jobs(self):
        adapter = LeverAdapter(companies=[{"token": "testco", "name": "TestCo"}])

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=MOCK_LEVER_RESPONSE)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncContextManager(mock_response))

        result = await adapter._scrape_company(mock_session, "testco", "TestCo")
        assert len(result) == 1
        assert result[0].title == "DevOps Engineer"
        assert result[0].source == "lever-testco"
```

- [ ] **Step 2: Implement Lever adapter**

```python
# sources/lever.py
"""Lever public postings API adapter — no auth required."""
from __future__ import annotations

import logging
from datetime import datetime

import aiohttp

from models.job import RawJob
from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)

LEVER_API = "https://api.lever.co/v0/postings"


class LeverAdapter(SourceAdapter):
    name = "lever"

    def __init__(self, companies: list[dict]):
        self.companies = companies

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        jobs: list[RawJob] = []
        errors: list[str] = []

        async with aiohttp.ClientSession() as session:
            for company in self.companies:
                try:
                    company_jobs = await self._scrape_company(
                        session, company["token"], company["name"]
                    )
                    jobs.extend(company_jobs)
                except Exception as e:
                    msg = f"Lever {company['name']}: {e}"
                    logger.warning(msg)
                    errors.append(msg)

        logger.info(f"Lever: scraped {len(jobs)} jobs from {len(self.companies)} companies")
        return SourceResult(jobs=jobs, errors=errors)

    async def _scrape_company(
        self, session: aiohttp.ClientSession, token: str, name: str
    ) -> list[RawJob]:
        url = f"{LEVER_API}/{token}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                logger.warning(f"Lever {name}: HTTP {resp.status}")
                return []
            data = await resp.json()

        if not isinstance(data, list):
            return []

        jobs: list[RawJob] = []
        for item in data:
            location = ""
            categories = item.get("categories", {})
            if isinstance(categories, dict):
                location = categories.get("location", "")

            jobs.append(
                RawJob(
                    title=item.get("text", ""),
                    company=name,
                    location=location,
                    description=item.get("descriptionPlain", ""),
                    url=item.get("hostedUrl", ""),
                    source=f"lever-{token}",
                )
            )

        return jobs
```

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/test_lever.py -v
git add sources/lever.py tests/test_lever.py
git commit -m "feat: add Lever public postings API adapter"
```

---

### Task 9: LinkedIn/Indeed Adapter (python-jobspy wrapper)

**Files:**
- Create: `sources/linkedin_indeed.py`
- Create: `tests/test_linkedin_indeed.py`

**Before writing:** Use context7 to look up `python-jobspy` current API. The key function is `scrape_jobs(site_name, search_term, location, results_wanted, hours_old)` returning a pandas DataFrame.

- [ ] **Step 1: Write failing test**

```python
# tests/test_linkedin_indeed.py
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from sources.linkedin_indeed import LinkedInIndeedAdapter


MOCK_DF = pd.DataFrame([
    {
        "title": "Cloud Engineer",
        "company": "Google",
        "location": "Remote",
        "description": "Cloud role with AWS",
        "job_url": "https://linkedin.com/jobs/123",
        "min_amount": 120000,
        "max_amount": 180000,
        "site": "linkedin",
    }
])


class TestLinkedInIndeedAdapter:
    @pytest.mark.asyncio
    async def test_scrape_converts_dataframe_to_raw_jobs(self):
        adapter = LinkedInIndeedAdapter(sites=["linkedin"])

        with patch("sources.linkedin_indeed.scrape_jobs", return_value=MOCK_DF):
            result = await adapter.scrape(["Cloud Engineer"], ["Remote"])

        assert len(result.jobs) == 1
        assert result.jobs[0].title == "Cloud Engineer"
        assert result.jobs[0].source == "linkedin"
        assert result.jobs[0].salary_min == 120000
```

- [ ] **Step 2: Implement adapter**

```python
# sources/linkedin_indeed.py
"""LinkedIn + Indeed adapter via python-jobspy library."""
from __future__ import annotations

import asyncio
import logging
import math
from concurrent.futures import ThreadPoolExecutor

from models.job import RawJob
from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)


def _safe_str(val) -> str | None:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    return str(val).strip() or None


def _safe_int(val) -> int | None:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


class LinkedInIndeedAdapter(SourceAdapter):
    name = "linkedin_indeed"

    def __init__(self, sites: list[str] | None = None, results_per_search: int = 20, hours_old: int = 24):
        self.sites = sites or ["linkedin", "indeed"]
        self.results_per_search = results_per_search
        self.hours_old = hours_old

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        jobs: list[RawJob] = []
        errors: list[str] = []

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=8) as pool:
            tasks = []
            for site in self.sites:
                for title in titles:
                    for location in locations:
                        tasks.append(
                            loop.run_in_executor(
                                pool, self._scrape_one, site, title, location
                            )
                        )

            results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                errors.append(str(result))
            elif isinstance(result, list):
                jobs.extend(result)

        logger.info(f"LinkedIn/Indeed: scraped {len(jobs)} jobs")
        return SourceResult(jobs=jobs, errors=errors)

    def _scrape_one(self, site: str, title: str, location: str) -> list[RawJob]:
        from jobspy import scrape_jobs

        try:
            df = scrape_jobs(
                site_name=[site],
                search_term=title,
                location=location,
                results_wanted=self.results_per_search,
                hours_old=self.hours_old,
            )
        except Exception as e:
            logger.warning(f"{site} scrape failed for '{title}' in '{location}': {e}")
            return []

        jobs: list[RawJob] = []
        for _, row in df.iterrows():
            raw_title = _safe_str(row.get("title"))
            raw_company = _safe_str(row.get("company"))
            if not raw_title or not raw_company:
                continue

            jobs.append(
                RawJob(
                    title=raw_title,
                    company=raw_company,
                    location=_safe_str(row.get("location")) or location,
                    description=_safe_str(row.get("description")),
                    salary_min=_safe_int(row.get("min_amount")),
                    salary_max=_safe_int(row.get("max_amount")),
                    url=_safe_str(row.get("job_url")) or "",
                    source=site,
                )
            )

        return jobs
```

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/test_linkedin_indeed.py -v
git add sources/linkedin_indeed.py tests/test_linkedin_indeed.py
git commit -m "feat: add LinkedIn/Indeed adapter via python-jobspy"
```

---

### Task 10: HackerNews "Who's Hiring" Adapter

**Files:**
- Create: `sources/hackernews.py`
- Create: `tests/test_hackernews.py`

**HN API:** Algolia `GET https://hn.algolia.com/api/v1/search?query="who is hiring"&tags=story` to find the thread, then `GET https://hn.algolia.com/api/v1/items/{story_id}` for all comments. Each top-level comment is a job posting in format: `Company | Role | Location | Remote`.

- [ ] **Step 1: Write failing test**

```python
# tests/test_hackernews.py
import pytest
from sources.hackernews import HackerNewsAdapter, parse_hn_comment


class TestHNParsing:
    def test_parse_standard_format(self):
        comment = "Anthropic | Cloud Engineer | San Francisco, CA | Remote OK\n\nWe are building..."
        result = parse_hn_comment(comment, "https://news.ycombinator.com/item?id=123")
        assert result is not None
        assert result.company == "Anthropic"
        assert result.title == "Cloud Engineer"
        assert "San Francisco" in result.location

    def test_parse_with_url(self):
        comment = "Google | DevOps Engineer | NYC | https://careers.google.com/jobs/123"
        result = parse_hn_comment(comment, "https://news.ycombinator.com/item?id=456")
        assert result is not None
        assert result.company == "Google"

    def test_skip_non_job_comment(self):
        comment = "This is just a regular comment about the thread."
        result = parse_hn_comment(comment, "https://news.ycombinator.com/item?id=789")
        assert result is None

    def test_skip_empty_comment(self):
        result = parse_hn_comment("", "https://news.ycombinator.com/item?id=0")
        assert result is None
```

- [ ] **Step 2: Implement HN adapter**

```python
# sources/hackernews.py
"""HackerNews 'Who is Hiring' monthly thread adapter via Algolia API."""
from __future__ import annotations

import logging
import re
from datetime import datetime

import aiohttp

from models.job import RawJob
from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)

ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search"
ALGOLIA_ITEM = "https://hn.algolia.com/api/v1/items"


def parse_hn_comment(text: str, fallback_url: str) -> RawJob | None:
    """Parse a HN job comment in format: Company | Role | Location | ..."""
    if not text or "|" not in text:
        return None

    first_line = text.split("\n")[0].strip()
    parts = [p.strip() for p in first_line.split("|")]

    if len(parts) < 2:
        return None

    company = parts[0]
    title = parts[1]
    location = parts[2] if len(parts) > 2 else "Not specified"

    # Skip if company or title look like non-job content
    if len(company) > 100 or len(title) > 100:
        return None
    if not company or not title:
        return None

    # Extract URL from the comment body if present
    url_match = re.search(r'https?://\S+', text)
    url = url_match.group(0) if url_match else fallback_url

    # Full comment (after first line) is the description
    lines = text.split("\n")
    description = "\n".join(lines[1:]).strip() if len(lines) > 1 else None

    return RawJob(
        title=title,
        company=company,
        location=location,
        description=description,
        url=url,
        source="hackernews",
    )


class HackerNewsAdapter(SourceAdapter):
    name = "hackernews"

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        jobs: list[RawJob] = []
        errors: list[str] = []

        try:
            async with aiohttp.ClientSession() as session:
                # Find the latest "Who is Hiring" thread
                thread_id = await self._find_latest_thread(session)
                if not thread_id:
                    return SourceResult(jobs=[], errors=["No 'Who is Hiring' thread found"])

                # Fetch all comments
                comments = await self._fetch_comments(session, thread_id)

                for comment in comments:
                    text = comment.get("text", "")
                    comment_id = comment.get("id", "")
                    fallback_url = f"https://news.ycombinator.com/item?id={comment_id}"

                    job = parse_hn_comment(text, fallback_url)
                    if job:
                        jobs.append(job)

        except Exception as e:
            msg = f"HackerNews: {e}"
            logger.warning(msg)
            errors.append(msg)

        logger.info(f"HackerNews: parsed {len(jobs)} jobs from Who's Hiring thread")
        return SourceResult(jobs=jobs, errors=errors)

    async def _find_latest_thread(self, session: aiohttp.ClientSession) -> int | None:
        params = {
            "query": '"Ask HN: Who is hiring?"',
            "tags": "story",
            "numericFilters": "created_at_i>0",
        }
        async with session.get(ALGOLIA_SEARCH, params=params) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()

        hits = data.get("hits", [])
        for hit in hits:
            title = hit.get("title", "")
            if "who is hiring" in title.lower() and "ask hn" in title.lower():
                return int(hit["objectID"])
        return None

    async def _fetch_comments(self, session: aiohttp.ClientSession, story_id: int) -> list[dict]:
        url = f"{ALGOLIA_ITEM}/{story_id}"
        async with session.get(url) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()

        # Only top-level children are job postings
        return data.get("children", [])
```

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/test_hackernews.py -v
git add sources/hackernews.py tests/test_hackernews.py
git commit -m "feat: add HackerNews Who's Hiring adapter via Algolia API"
```

---

### Task 11: RemoteOK Adapter

**Files:**
- Create: `sources/remoteok.py`
- Create: `tests/test_remoteok.py`

**RemoteOK API:** `GET https://remoteok.com/api` — public JSON, no auth. Returns array of job objects.

- [ ] **Step 1: Write failing test**

```python
# tests/test_remoteok.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from sources.remoteok import RemoteOKAdapter
from tests.test_greenhouse import AsyncContextManager


MOCK_REMOTEOK_RESPONSE = [
    {"legal": "terms"},  # First item is always metadata
    {
        "id": "123",
        "company": "TestCo",
        "position": "DevOps Engineer",
        "location": "Worldwide",
        "description": "Remote DevOps role with K8s",
        "url": "https://remoteok.com/jobs/123",
        "salary_min": 100000,
        "salary_max": 150000,
    },
]


class TestRemoteOKAdapter:
    @pytest.mark.asyncio
    async def test_scrape_returns_jobs(self):
        adapter = RemoteOKAdapter()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=MOCK_REMOTEOK_RESPONSE)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncContextManager(mock_response))

        result = await adapter._fetch_jobs(mock_session)
        assert len(result) == 1
        assert result[0].title == "DevOps Engineer"
        assert result[0].source == "remoteok"
```

- [ ] **Step 2: Implement RemoteOK adapter**

```python
# sources/remoteok.py
"""RemoteOK public JSON API adapter."""
from __future__ import annotations

import logging

import aiohttp

from models.job import RawJob
from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)

REMOTEOK_API = "https://remoteok.com/api"


class RemoteOKAdapter(SourceAdapter):
    name = "remoteok"

    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        jobs: list[RawJob] = []
        errors: list[str] = []

        try:
            async with aiohttp.ClientSession() as session:
                jobs = await self._fetch_jobs(session)
        except Exception as e:
            msg = f"RemoteOK: {e}"
            logger.warning(msg)
            errors.append(msg)

        logger.info(f"RemoteOK: fetched {len(jobs)} jobs")
        return SourceResult(jobs=jobs, errors=errors)

    async def _fetch_jobs(self, session: aiohttp.ClientSession) -> list[RawJob]:
        headers = {"User-Agent": "IntelligentJobSearch/1.0"}
        async with session.get(REMOTEOK_API, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                logger.warning(f"RemoteOK: HTTP {resp.status}")
                return []
            data = await resp.json(content_type=None)

        jobs: list[RawJob] = []
        for item in data:
            # Skip metadata items (first item and items without 'position')
            if "position" not in item:
                continue

            salary_min = item.get("salary_min")
            salary_max = item.get("salary_max")

            jobs.append(
                RawJob(
                    title=item.get("position", ""),
                    company=item.get("company", ""),
                    location=item.get("location", "Remote"),
                    description=item.get("description", ""),
                    salary_min=int(salary_min) if salary_min else None,
                    salary_max=int(salary_max) if salary_max else None,
                    url=item.get("url", ""),
                    source="remoteok",
                )
            )

        return jobs
```

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/test_remoteok.py -v
git add sources/remoteok.py tests/test_remoteok.py
git commit -m "feat: add RemoteOK public JSON API adapter"
```

---

### Task 12: Remaining Source Adapters (Wellfound, BuiltIn, Dice, YC, AI Jobs)

**Files:**
- Create: `sources/wellfound.py`
- Create: `sources/builtin.py`
- Create: `sources/dice.py`
- Create: `sources/yc_startup.py`
- Create: `sources/ai_jobs.py`
- Create: `sources/ashby.py`

These adapters follow the same pattern as Greenhouse/Lever/RemoteOK. Each implements `SourceAdapter` with async `scrape()`.

- [ ] **Step 1: Implement each adapter**

For each source, look up its current API or scraping method via context7 or web search before implementing. Each adapter should:
1. Implement the `SourceAdapter` interface from `sources/base.py`
2. Use `aiohttp` for HTTP requests
3. Parse responses into `RawJob` objects
4. Handle errors gracefully (return empty list + error message)
5. Log results

**Wellfound:** Scrape `https://wellfound.com/role/l/{location}/{title}` — HTML parsing with BeautifulSoup.
**BuiltIn:** Scrape `https://builtin.com/jobs` with location/title filters — HTML parsing.
**Dice:** Scrape `https://www.dice.com/jobs` with search params — HTML parsing.
**YC:** Scrape `https://www.workatastartup.com/jobs` — may have JSON API.
**AI Jobs:** Scrape `https://ai-jobs.net` — HTML parsing.
**Ashby:** Similar to Greenhouse — `GET https://api.ashbyhq.com/posting-api/job-board/{board}` — public JSON.

Each adapter file follows the same structure as `sources/greenhouse.py`. Create a basic test for each (mock HTTP, verify RawJob output).

- [ ] **Step 2: Run all tests and commit**

```bash
pytest tests/ -v
git add sources/ tests/
git commit -m "feat: add Wellfound, BuiltIn, Dice, YC, AI Jobs, and Ashby source adapters"
```

---

### Task 13: Scraper Orchestrator

**Files:**
- Create: `sources/orchestrator.py`
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_orchestrator.py
import pytest
from unittest.mock import AsyncMock
from sources.orchestrator import ScraperOrchestrator
from sources.base import SourceAdapter, SourceResult
from models.job import RawJob


class FakeSource(SourceAdapter):
    def __init__(self, name_: str, jobs_: list[RawJob]):
        self.name = name_
        self._jobs = jobs_

    async def scrape(self, titles, locations):
        return SourceResult(jobs=self._jobs, errors=[])


class FailingSource(SourceAdapter):
    name = "failing"

    async def scrape(self, titles, locations):
        raise ConnectionError("Source is down")


class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_scrape_all_sources_in_parallel(self):
        source_a = FakeSource("source_a", [
            RawJob(title="Job1", company="Co1", location="NYC",
                   url="https://a.com/1", source="source_a"),
        ])
        source_b = FakeSource("source_b", [
            RawJob(title="Job2", company="Co2", location="SF",
                   url="https://b.com/1", source="source_b"),
        ])

        orchestrator = ScraperOrchestrator(adapters=[source_a, source_b])
        result = await orchestrator.scrape_all(["Cloud Engineer"], ["Remote"])
        assert len(result.jobs) == 2
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_dedup_by_fingerprint(self):
        job = RawJob(title="Cloud Eng", company="Google", location="Remote",
                     url="https://a.com", source="source_a")
        source_a = FakeSource("source_a", [job])
        source_b = FakeSource("source_b", [
            RawJob(title="Cloud Eng", company="Google", location="Remote",
                   url="https://b.com", source="source_b"),
        ])

        orchestrator = ScraperOrchestrator(adapters=[source_a, source_b])
        result = await orchestrator.scrape_all(["Cloud Eng"], ["Remote"])
        assert len(result.jobs) == 1  # deduped

    @pytest.mark.asyncio
    async def test_one_source_failure_doesnt_kill_pipeline(self):
        good = FakeSource("good", [
            RawJob(title="Job1", company="Co1", location="NYC",
                   url="https://a.com", source="good"),
        ])
        bad = FailingSource()

        orchestrator = ScraperOrchestrator(adapters=[good, bad])
        result = await orchestrator.scrape_all(["Job"], ["NYC"])
        assert len(result.jobs) == 1
        assert len(result.errors) == 1
        assert "Source is down" in result.errors[0]
```

- [ ] **Step 2: Implement orchestrator**

```python
# sources/orchestrator.py
"""Scraper orchestrator — runs all source adapters in parallel, deduplicates results."""
from __future__ import annotations

import asyncio
import logging

from models.job import RawJob
from sources.base import SourceAdapter, SourceResult

logger = logging.getLogger(__name__)


class ScraperOrchestrator:
    def __init__(self, adapters: list[SourceAdapter]):
        self.adapters = adapters

    async def scrape_all(
        self, titles: list[str], locations: list[str],
        known_fingerprints: set[str] | None = None,
    ) -> SourceResult:
        all_jobs: list[RawJob] = []
        all_errors: list[str] = []

        # Run all adapters in parallel
        tasks = [
            self._safe_scrape(adapter, titles, locations)
            for adapter in self.adapters
        ]
        results = await asyncio.gather(*tasks)

        for result in results:
            all_jobs.extend(result.jobs)
            all_errors.extend(result.errors)

        # Deduplicate by fingerprint
        seen: set[str] = set(known_fingerprints or set())
        unique_jobs: list[RawJob] = []
        dupes = 0
        for job in all_jobs:
            if job.fingerprint not in seen:
                seen.add(job.fingerprint)
                unique_jobs.append(job)
            else:
                dupes += 1

        logger.info(
            f"Orchestrator: {len(all_jobs)} total, {dupes} duplicates removed, "
            f"{len(unique_jobs)} unique jobs"
        )

        return SourceResult(jobs=unique_jobs, errors=all_errors)

    async def _safe_scrape(
        self, adapter: SourceAdapter, titles: list[str], locations: list[str]
    ) -> SourceResult:
        try:
            return await adapter.scrape(titles, locations)
        except Exception as e:
            msg = f"{adapter.name}: {e}"
            logger.error(msg)
            return SourceResult(jobs=[], errors=[msg])
```

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/test_orchestrator.py -v
git add sources/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add scraper orchestrator with parallel execution and dedup"
```

---

## Phase 3: Screening Engine

### Task 14: Stage 1 — Regex Fast Filter

**Files:**
- Create: `screening/__init__.py`
- Create: `screening/stage1.py`
- Create: `tests/test_stage1.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_stage1.py
import pytest
from models.job import RawJob
from screening.stage1 import Stage1Filter, FilterResult


def make_job(**kwargs) -> RawJob:
    defaults = {
        "title": "Cloud Engineer",
        "company": "Google",
        "location": "San Francisco, CA",
        "description": "We need a cloud engineer with AWS and Kubernetes experience. 2+ years preferred.",
        "url": "https://example.com",
        "source": "greenhouse-google",
    }
    defaults.update(kwargs)
    return RawJob(**defaults)


class TestStage1Filter:
    def test_good_job_passes(self):
        f = Stage1Filter()
        result = f.filter_job(make_job())
        assert result.passed is True

    def test_rejects_senior_title(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(title="Senior Cloud Engineer"))
        assert result.passed is False
        assert "senior" in result.reason.lower()

    def test_rejects_clearance_required(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(description="Must have TS/SCI clearance"))
        assert result.passed is False
        assert "clearance" in result.reason.lower() or "ts/sci" in result.reason.lower()

    def test_rejects_no_sponsorship(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(description="We will not sponsor visas"))
        assert result.passed is False

    def test_rejects_5_plus_years(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(description="Requires 5+ years of experience"))
        assert result.passed is False

    def test_rejects_empty_description(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(description=None))
        assert result.passed is False
        assert "empty" in result.reason.lower()

    def test_rejects_below_salary_floor(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(salary_max=50000))
        assert result.passed is False

    def test_rejects_missing_domain_keywords(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(
            title="Marketing Coordinator",
            description="Looking for a marketing person.",
        ))
        assert result.passed is False

    def test_batch_filter(self):
        f = Stage1Filter()
        jobs = [
            make_job(title="Cloud Engineer"),
            make_job(title="Senior Principal Architect"),
            make_job(title="DevOps Engineer"),
        ]
        passed, rejected = f.filter_batch(jobs)
        assert len(passed) == 2
        assert len(rejected) == 1
```

- [ ] **Step 2: Implement Stage 1 filter**

```python
# screening/__init__.py
"""Two-stage screening engine."""

# screening/stage1.py
"""Stage 1: Fast regex-based filtering — no API calls, instant."""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass

from models.job import RawJob
from config import (
    EXCLUDE_TITLE_KEYWORDS, EXCLUDE_DESC_PATTERNS,
    REQUIRE_ONE_OF, SALARY_FLOOR, TITLE_DOMAIN_KEYWORDS,
)

logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    job: RawJob
    passed: bool
    reason: str
    stage: str = "stage1"


class Stage1Filter:

    def filter_job(self, job: RawJob) -> FilterResult:
        title_lower = job.title.lower()
        desc_lower = (job.description or "").lower()

        # 1. Empty description
        if not job.description or not job.description.strip():
            return FilterResult(job=job, passed=False,
                                reason="Empty description — cannot screen",
                                stage="stage1_empty_desc")

        # 2. Title exclusion (word-boundary matching)
        for kw in EXCLUDE_TITLE_KEYWORDS:
            pattern = r'\b' + re.escape(kw.strip().rstrip('.')) + r'\b'
            if re.search(pattern, title_lower):
                return FilterResult(job=job, passed=False,
                                    reason=f"Title exclusion: '{kw}' matched in '{job.title}'",
                                    stage="stage1_title")

        # 3. Title domain check — at least one domain keyword
        has_domain = any(
            re.search(r'\b' + re.escape(kw) + r'\b', title_lower)
            for kw in TITLE_DOMAIN_KEYWORDS
        )
        if not has_domain:
            return FilterResult(job=job, passed=False,
                                reason=f"No domain keyword in title: '{job.title}'",
                                stage="stage1_title_domain")

        # 4. Description hard-stops
        for pattern in EXCLUDE_DESC_PATTERNS:
            if pattern.lower() in desc_lower:
                return FilterResult(job=job, passed=False,
                                    reason=f"Description hard-stop: '{pattern}'",
                                    stage="stage1_desc")

        # 5. Salary floor
        if job.salary_max is not None and job.salary_max < SALARY_FLOOR:
            return FilterResult(job=job, passed=False,
                                reason=f"Salary max ${job.salary_max:,} below floor ${SALARY_FLOOR:,}",
                                stage="stage1_salary")

        # 6. Must-have keyword check
        combined = title_lower + " " + desc_lower
        has_required = any(kw.lower() in combined for kw in REQUIRE_ONE_OF)
        if not has_required:
            return FilterResult(job=job, passed=False,
                                reason="No required keywords found in title or description",
                                stage="stage1_keywords")

        return FilterResult(job=job, passed=True, reason="Passed all Stage 1 filters",
                            stage="stage1_pass")

    def filter_batch(self, jobs: list[RawJob]) -> tuple[list[RawJob], list[FilterResult]]:
        passed: list[RawJob] = []
        rejected: list[FilterResult] = []

        for job in jobs:
            result = self.filter_job(job)
            if result.passed:
                passed.append(job)
            else:
                rejected.append(result)

        logger.info(f"Stage 1: {len(passed)} passed, {len(rejected)} rejected out of {len(jobs)}")
        return passed, rejected
```

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/test_stage1.py -v
git add screening/ tests/test_stage1.py
git commit -m "feat: add Stage 1 regex filter with title/desc/salary/keyword checks and audit logging"
```

---

### Task 15: Stage 2 — Claude CLI Precision Screen

**Files:**
- Create: `screening/stage2.py`
- Create: `prompts/screening.md`
- Create: `tests/test_stage2.py`

- [ ] **Step 1: Create screening prompt template**

```markdown
<!-- prompts/screening.md -->
You are a job screening assistant. You evaluate job descriptions against a candidate's profile to determine fit.

## Candidate Profile Summary

{{profile_summary}}

## Instructions

For each job below, evaluate:
1. Does the candidate meet the minimum experience requirements?
2. Are there any hard disqualifiers (clearance, citizenship, explicit no-sponsorship)?
3. How well do the required skills match the candidate's skills?
4. Is the seniority level appropriate (junior/associate level)?

Return a JSON array with one object per job. Each object MUST have exactly these fields:

```json
{
  "fingerprint": "company||title (lowercase)",
  "verdict": "APPLY" | "SKIP" | "MAYBE",
  "confidence": 1-5,
  "reasoning": "One sentence explanation",
  "match_signals": ["skill1", "skill2"],
  "risk_flags": ["potential concern"],
  "suggested_angle": "Which resume framing works best"
}
```

Verdict guidelines:
- APPLY: Good fit, candidate should apply. Confidence 3-5.
- MAYBE: Borderline — some concerns but worth reviewing. Confidence 2-3.
- SKIP: Not a fit — hard disqualifiers or severe mismatch. Confidence 1-2.

Be generous with APPLY for roles where the candidate has 60%+ skill match.
Flag but don't auto-reject "preferred" experience requirements (e.g., "3+ years preferred").
Auto-SKIP: explicit no-sponsorship, security clearance required, 5+ years required, senior/staff level.

## Jobs to Screen

{{jobs_json}}

Return ONLY the JSON array. No markdown, no commentary.
```

- [ ] **Step 2: Write test for Stage 2**

```python
# tests/test_stage2.py
import pytest
import json
from unittest.mock import patch, MagicMock
from screening.stage2 import Stage2Screen
from models.job import RawJob


MOCK_CLAUDE_OUTPUT = json.dumps([
    {
        "fingerprint": "google||cloud engineer",
        "verdict": "APPLY",
        "confidence": 4,
        "reasoning": "Strong match: AWS + K8s experience aligns well",
        "match_signals": ["AWS", "Kubernetes", "Terraform"],
        "risk_flags": [],
        "suggested_angle": "AI Infrastructure",
    }
])


class TestStage2Screen:
    def test_parse_claude_response(self):
        screen = Stage2Screen(profile_path="profile.yaml")
        results = screen._parse_response(MOCK_CLAUDE_OUTPUT)
        assert len(results) == 1
        assert results[0]["verdict"] == "APPLY"
        assert results[0]["confidence"] == 4

    def test_parse_handles_invalid_json(self):
        screen = Stage2Screen(profile_path="profile.yaml")
        results = screen._parse_response("not valid json at all")
        assert results == []

    def test_parse_handles_json_in_markdown(self):
        screen = Stage2Screen(profile_path="profile.yaml")
        wrapped = f"```json\n{MOCK_CLAUDE_OUTPUT}\n```"
        results = screen._parse_response(wrapped)
        assert len(results) == 1
```

- [ ] **Step 3: Implement Stage 2 screen**

```python
# screening/stage2.py
"""Stage 2: Claude CLI precision screening — profile-aware evaluation."""
from __future__ import annotations

import json
import logging
import re
import subprocess
import yaml
from pathlib import Path

from models.job import RawJob, ScreenedJob, ScreeningVerdict
from config import SCREENING_BATCH_SIZE

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "screening.md"


class Stage2Screen:
    def __init__(self, profile_path: str = "profile.yaml"):
        self.profile_path = profile_path
        self._profile_summary: str | None = None

    def _load_profile_summary(self) -> str:
        if self._profile_summary:
            return self._profile_summary

        with open(self.profile_path) as f:
            profile = yaml.safe_load(f)

        personal = profile.get("personal", {})
        parts = [
            f"Name: {personal.get('name', '')}",
            f"Visa: {personal.get('visa', '')}",
            f"Education: {', '.join(e.get('degree', '') + ' @ ' + e.get('school', '') for e in profile.get('education', []))}",
            f"Experience: {', '.join(e.get('company', '') + ' (' + e.get('period', '') + ')' for e in profile.get('experiences', []))}",
            f"Certifications: {', '.join(c.get('name', '') for c in profile.get('certifications', []))}",
        ]

        skills = profile.get("skills", {})
        for category, items in skills.items():
            parts.append(f"Skills ({category}): {', '.join(items[:5])}")

        self._profile_summary = "\n".join(parts)
        return self._profile_summary

    def screen_batch(self, jobs: list[RawJob]) -> list[ScreenedJob]:
        """Screen a batch of jobs using Claude CLI. Returns ScreenedJob list."""
        all_screened: list[ScreenedJob] = []

        # Process in batches
        for i in range(0, len(jobs), SCREENING_BATCH_SIZE):
            batch = jobs[i:i + SCREENING_BATCH_SIZE]
            batch_results = self._screen_one_batch(batch)

            # Match results back to jobs by fingerprint
            result_map = {r["fingerprint"]: r for r in batch_results}
            for job in batch:
                result = result_map.get(job.fingerprint)
                if result:
                    try:
                        screened = ScreenedJob(
                            **job.model_dump(),
                            verdict=ScreeningVerdict(result["verdict"]),
                            confidence=result.get("confidence", 3),
                            reasoning=result.get("reasoning", ""),
                            match_signals=result.get("match_signals", []),
                            risk_flags=result.get("risk_flags", []),
                            suggested_angle=result.get("suggested_angle", ""),
                        )
                        all_screened.append(screened)
                    except Exception as e:
                        logger.warning(f"Failed to create ScreenedJob for {job.fingerprint}: {e}")
                        # Default to APPLY on parse error
                        all_screened.append(self._default_apply(job))
                else:
                    # Job not in Claude response — default to MAYBE
                    all_screened.append(self._default_maybe(job))

        return all_screened

    def _screen_one_batch(self, jobs: list[RawJob]) -> list[dict]:
        prompt_template = PROMPT_PATH.read_text()

        jobs_data = []
        for job in jobs:
            desc = (job.description or "")[:3000]  # Truncate long descriptions
            jobs_data.append({
                "fingerprint": job.fingerprint,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "description": desc,
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "source": job.source,
            })

        prompt = prompt_template.replace(
            "{{profile_summary}}", self._load_profile_summary()
        ).replace(
            "{{jobs_json}}", json.dumps(jobs_data, indent=2)
        )

        # Invoke Claude CLI
        try:
            result = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "text"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                logger.error(f"Claude CLI error: {result.stderr}")
                return []
            return self._parse_response(result.stdout)
        except subprocess.TimeoutExpired:
            logger.error("Claude CLI timed out")
            return []
        except FileNotFoundError:
            logger.error("Claude CLI not found — is it installed and in PATH?")
            return []

    def _parse_response(self, text: str) -> list[dict]:
        text = text.strip()

        # Strip markdown code fences if present
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            text = match.group(1).strip()

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            return []
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse Claude response as JSON: {text[:200]}")
            return []

    def _default_apply(self, job: RawJob) -> ScreenedJob:
        return ScreenedJob(
            **job.model_dump(),
            verdict=ScreeningVerdict.APPLY,
            confidence=2,
            reasoning="Claude screening failed — defaulting to APPLY for manual review",
            suggested_angle="",
        )

    def _default_maybe(self, job: RawJob) -> ScreenedJob:
        return ScreenedJob(
            **job.model_dump(),
            verdict=ScreeningVerdict.MAYBE,
            confidence=2,
            reasoning="Not returned in Claude screening batch — flagged for review",
            suggested_angle="",
        )
```

- [ ] **Step 4: Run tests and commit**

```bash
pytest tests/test_stage2.py -v
git add screening/stage2.py prompts/screening.md tests/test_stage2.py
git commit -m "feat: add Stage 2 Claude CLI precision screening with prompt template"
```

---

## Phase 4: Google Sheets + Main Pipeline

### Task 16: Sheets Client

**Files:**
- Create: `sheets/__init__.py`
- Create: `sheets/client.py`
- Create: `sheets/daily.py`
- Create: `sheets/audit.py`
- Create: `sheets/applied.py`

**Before writing:** Use context7 to look up `gspread` v6+ API. Key methods: `open()`, `worksheet()`, `append_rows()`, `clear()`, `batch_update()`, `get_all_values()`.

- [ ] **Step 1: Implement Sheets client and tab modules**

```python
# sheets/__init__.py
"""Google Sheets integration — single UI for the user."""

# sheets/client.py
"""Google Sheets and Drive client initialization."""
from __future__ import annotations

import logging
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from config import (
    GOOGLE_SHEETS_CREDS_FILE, SPREADSHEET_NAME,
    DAILY_HEADERS, AUDIT_HEADERS, APPLIED_HEADERS,
)

logger = logging.getLogger(__name__)

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsClient:
    def __init__(self):
        self.creds = Credentials.from_service_account_file(
            GOOGLE_SHEETS_CREDS_FILE, scopes=SCOPES
        )
        self.gc = gspread.authorize(self.creds)
        self.spreadsheet = self._get_or_create_spreadsheet()
        self.drive_service = build("drive", "v3", credentials=self.creds)

    def _get_or_create_spreadsheet(self) -> gspread.Spreadsheet:
        try:
            return self.gc.open(SPREADSHEET_NAME)
        except gspread.SpreadsheetNotFound:
            logger.info(f"Creating new spreadsheet: {SPREADSHEET_NAME}")
            ss = self.gc.create(SPREADSHEET_NAME)
            # Create tabs with headers
            daily = ss.sheet1
            daily.update_title("Daily")
            daily.append_row(DAILY_HEADERS)

            audit = ss.add_worksheet(title="Audit", rows=1000, cols=len(AUDIT_HEADERS))
            audit.append_row(AUDIT_HEADERS)

            applied = ss.add_worksheet(title="Applied", rows=1000, cols=len(APPLIED_HEADERS))
            applied.append_row(APPLIED_HEADERS)

            return ss

    def get_daily_sheet(self) -> gspread.Worksheet:
        try:
            return self.spreadsheet.worksheet("Daily")
        except gspread.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet("Daily", rows=1000, cols=len(DAILY_HEADERS))
            ws.append_row(DAILY_HEADERS)
            return ws

    def get_audit_sheet(self) -> gspread.Worksheet:
        try:
            return self.spreadsheet.worksheet("Audit")
        except gspread.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet("Audit", rows=1000, cols=len(AUDIT_HEADERS))
            ws.append_row(AUDIT_HEADERS)
            return ws

    def get_applied_sheet(self) -> gspread.Worksheet:
        try:
            return self.spreadsheet.worksheet("Applied")
        except gspread.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet("Applied", rows=1000, cols=len(APPLIED_HEADERS))
            ws.append_row(APPLIED_HEADERS)
            return ws
```

```python
# sheets/daily.py
"""Daily tab operations — ephemeral, cleared each run."""
from __future__ import annotations

import logging
from datetime import date

import gspread

from config import DAILY_HEADERS
from models.job import ScreenedJob

logger = logging.getLogger(__name__)


def clear_and_write_headers(ws: gspread.Worksheet) -> None:
    ws.clear()
    ws.append_row(DAILY_HEADERS)


def write_screened_jobs(ws: gspread.Worksheet, jobs: list[ScreenedJob]) -> None:
    rows = []
    today = date.today().isoformat()

    for job in jobs:
        salary = ""
        if job.salary_min and job.salary_max:
            salary = f"${job.salary_min:,} - ${job.salary_max:,}"
        elif job.salary_min:
            salary = f"${job.salary_min:,}+"

        rows.append([
            today,                                # Date Scraped
            job.company,                          # Company
            job.title,                            # Job Title
            job.location,                         # Location
            job.source,                           # Source
            job.confidence,                       # Confidence
            job.reasoning,                        # AI Reasoning
            job.suggested_angle,                  # Suggested Angle
            ", ".join(job.risk_flags),            # Risk Flags
            ", ".join(job.match_signals),         # Match Signals
            salary,                               # Salary Range
            job.url,                              # Apply Link
            "",                                   # Status (user fills)
            "",                                   # Notes (user fills)
        ])

    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info(f"Daily tab: wrote {len(rows)} jobs")


def get_apply_jobs(ws: gspread.Worksheet) -> list[dict]:
    """Read Daily tab and return jobs where Status = 'Apply'."""
    all_rows = ws.get_all_records()
    return [row for row in all_rows if str(row.get("Status", "")).strip().lower() == "apply"]
```

```python
# sheets/audit.py
"""Audit tab operations — ephemeral, cleared each run."""
from __future__ import annotations

import logging
import gspread

from config import AUDIT_HEADERS
from screening.stage1 import FilterResult

logger = logging.getLogger(__name__)


def clear_and_write_headers(ws: gspread.Worksheet) -> None:
    ws.clear()
    ws.append_row(AUDIT_HEADERS)


def write_rejections(ws: gspread.Worksheet, rejections: list[FilterResult]) -> None:
    rows = []
    for r in rejections:
        rows.append([
            r.job.company,     # Company
            r.job.title,       # Job Title
            r.stage,           # Killed At
            r.reason,          # Reason
            r.job.source,      # Source
            r.job.url,         # Apply Link
        ])

    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info(f"Audit tab: wrote {len(rows)} rejections")
```

```python
# sheets/applied.py
"""Applied tab operations — persistent, grows over time."""
from __future__ import annotations

import logging
from datetime import date, timedelta

import gspread

from config import APPLIED_HEADERS
from models.job import ScreenedJob

logger = logging.getLogger(__name__)


def add_job(
    ws: gspread.Worksheet,
    job: ScreenedJob,
    resume_link: str,
    cover_letter_link: str,
    angle_used: str,
) -> None:
    today = date.today()
    followup = today + timedelta(days=7)

    row = [
        today.isoformat(),           # Date Applied
        job.company,                  # Company
        job.title,                    # Job Title
        job.location,                 # Location
        resume_link,                  # Resume Link
        cover_letter_link,            # Cover Letter Link
        job.url,                      # Apply Link
        angle_used,                   # Angle Used
        job.confidence,               # Screen Confidence
        job.source,                   # Source
        "Ready to Apply",            # Status
        "",                           # Days Waiting
        followup.isoformat(),         # Follow-up Date
        "No",                         # Follow-up Sent
        "",                           # Notes
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")


def get_all_applied(ws: gspread.Worksheet) -> list[dict]:
    return ws.get_all_records()
```

- [ ] **Step 2: Commit**

```bash
git add sheets/
git commit -m "feat: add Google Sheets client and tab operations (daily, audit, applied)"
```

---

### Task 17: Main Pipeline

**Files:**
- Create: `main.py`

- [ ] **Step 1: Implement main.py**

```python
# main.py
"""
============================================================
  INTELLIGENT JOB SEARCH — Main Pipeline
============================================================
  1. Validate config + credentials (fail-fast)
  2. Save yesterday's Daily/Audit data to SQLite
  3. Clear Daily + Audit tabs
  4. Parallel scrape all sources
  5. Dedup (cross-source + against SQLite)
  6. Stage 1: Regex fast filter
  7. Bulk save to SQLite
  8. Stage 2: Claude CLI precision screen
  9. Write to Daily + Audit tabs
  10. Print run summary
============================================================
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

import yaml

from config import (
    TARGET_TITLES, LOCATIONS, DB_FILE,
    SCREENING_CONFIDENCE_THRESHOLD,
)
from db.database import Database
from models.job import ScreenedJob, ScreeningVerdict
from screening.stage1 import Stage1Filter
from screening.stage2 import Stage2Screen
from sheets.client import SheetsClient
from sheets import daily as daily_ops, audit as audit_ops
from sources.orchestrator import ScraperOrchestrator
from sources.greenhouse import GreenhouseAdapter
from sources.lever import LeverAdapter
from sources.linkedin_indeed import LinkedInIndeedAdapter
from sources.hackernews import HackerNewsAdapter
from sources.remoteok import RemoteOKAdapter

# Fix Windows console encoding
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            f"logs/run_{date.today().isoformat()}.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)


def load_target_companies() -> dict:
    path = Path("target_companies.yaml")
    if not path.exists():
        return {"greenhouse": [], "lever": [], "ashby": []}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def build_adapters(companies: dict) -> list:
    adapters = []

    gh = companies.get("greenhouse", [])
    if gh:
        adapters.append(GreenhouseAdapter(companies=gh))

    lv = companies.get("lever", [])
    if lv:
        adapters.append(LeverAdapter(companies=lv))

    adapters.append(LinkedInIndeedAdapter())
    adapters.append(HackerNewsAdapter())
    adapters.append(RemoteOKAdapter())

    return adapters


def print_summary(
    total_scraped: int, dupes: int, stage1_passed: int, stage1_rejected: int,
    stage2_results: list[ScreenedJob], errors: list[str],
) -> None:
    apply_count = sum(1 for j in stage2_results if j.verdict == ScreeningVerdict.APPLY)
    maybe_count = sum(1 for j in stage2_results if j.verdict == ScreeningVerdict.MAYBE)
    skip_count = sum(1 for j in stage2_results if j.verdict == ScreeningVerdict.SKIP)

    print("\n" + "=" * 55)
    print("  INTELLIGENT JOB SEARCH — Run Summary")
    print(f"  {date.today().isoformat()}")
    print("=" * 55)
    print(f"\n  Total scraped:      {total_scraped}")
    print(f"  Duplicates removed: {dupes}")
    print(f"\n  STAGE 1 FILTER")
    print(f"  ├── Passed:    {stage1_passed}")
    print(f"  └── Rejected:  {stage1_rejected}")
    print(f"\n  STAGE 2 CLAUDE SCREEN")
    print(f"  ├── APPLY:  {apply_count}")
    print(f"  ├── MAYBE:  {maybe_count}")
    print(f"  └── SKIP:   {skip_count}")
    print(f"\n  → {apply_count + maybe_count} jobs written to Daily tab")
    if errors:
        print(f"\n  ⚠ {len(errors)} source errors (check logs)")
    print("=" * 55 + "\n")


async def run_pipeline():
    # ── Fail-fast validation ──
    Path("logs").mkdir(exist_ok=True)

    if not Path("profile.yaml").exists():
        logger.error("profile.yaml not found. Run update_profile.py first.")
        sys.exit(1)

    # ── Initialize ──
    db = Database(DB_FILE)
    db.initialize()

    sheets = SheetsClient()
    daily_ws = sheets.get_daily_sheet()
    audit_ws = sheets.get_audit_sheet()

    # ── Save yesterday's data to SQLite, then clear ──
    daily_ops.clear_and_write_headers(daily_ws)
    audit_ops.clear_and_write_headers(audit_ws)

    # ── Scrape ──
    companies = load_target_companies()
    adapters = build_adapters(companies)
    orchestrator = ScraperOrchestrator(adapters)

    known_fps = db.get_known_fingerprints(set())  # Get all known fingerprints
    scrape_result = await orchestrator.scrape_all(
        TARGET_TITLES, LOCATIONS, known_fingerprints=known_fps,
    )

    total_scraped = len(scrape_result.jobs) + len(known_fps)  # approximate
    unique_jobs = scrape_result.jobs

    # ── Stage 1: Regex filter ──
    stage1 = Stage1Filter()
    passed_jobs, rejected = stage1.filter_batch(unique_jobs)

    # Save all jobs to SQLite
    db.save_jobs(unique_jobs)

    # Save audit entries for rejected jobs
    today_str = date.today().isoformat()
    audit_entries = [
        {
            "job_fingerprint": r.job.fingerprint,
            "company": r.job.company,
            "title": r.job.title,
            "source": r.job.source,
            "stage": r.stage,
            "verdict": "REJECT",
            "reason": r.reason,
            "confidence": None,
            "run_date": today_str,
        }
        for r in rejected
    ]
    if audit_entries:
        db.save_audit_entries_bulk(audit_entries)

    # ── Stage 2: Claude CLI screen ──
    stage2 = Stage2Screen(profile_path="profile.yaml")
    screened_jobs = stage2.screen_batch(passed_jobs)

    # Save stage 2 audit entries
    stage2_audit = [
        {
            "job_fingerprint": j.fingerprint,
            "company": j.company,
            "title": j.title,
            "source": j.source,
            "stage": "stage2_claude",
            "verdict": j.verdict.value,
            "reason": j.reasoning,
            "confidence": j.confidence,
            "run_date": today_str,
        }
        for j in screened_jobs
    ]
    if stage2_audit:
        db.save_audit_entries_bulk(stage2_audit)

    # ── Write to Sheets ──
    # Daily tab: APPLY + MAYBE jobs
    daily_jobs = [
        j for j in screened_jobs
        if j.verdict in (ScreeningVerdict.APPLY, ScreeningVerdict.MAYBE)
    ]
    daily_ops.write_screened_jobs(daily_ws, daily_jobs)

    # Audit tab: Stage 1 rejections + Stage 2 SKIP jobs
    audit_ops.write_rejections(audit_ws, rejected)
    # Also write Stage 2 SKIPs to audit
    stage2_skips = [
        type("FilterResult", (), {
            "job": j, "stage": "stage2_claude",
            "reason": j.reasoning, "passed": False,
        })()
        for j in screened_jobs if j.verdict == ScreeningVerdict.SKIP
    ]
    if stage2_skips:
        audit_ops.write_rejections(audit_ws, stage2_skips)

    # ── Summary ──
    print_summary(
        total_scraped=len(unique_jobs),
        dupes=0,  # orchestrator already deduped
        stage1_passed=len(passed_jobs),
        stage1_rejected=len(rejected),
        stage2_results=screened_jobs,
        errors=scrape_result.errors,
    )

    db.close()


def main():
    asyncio.run(run_pipeline())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test that main.py compiles**

```bash
python -m py_compile main.py
```

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add main pipeline — scrape, filter, screen, write to Sheets"
```

---

## Phase 5: Resume/Cover Letter Engine

### Task 18: Prompt Templates

**Files:**
- Create: `prompts/resume.md`
- Create: `prompts/cover_letter.md`

- [ ] **Step 1: Create resume prompt template**

```markdown
<!-- prompts/resume.md -->
You are an expert resume writer. Generate a tailored resume for the candidate based on their profile and the job description.

## Candidate Profile

{{profile_yaml}}

## Job Description

Company: {{company}}
Title: {{title}}
Location: {{location}}
Source: {{source}}
Screening notes: {{screening_notes}}

Description:
{{description}}

## Instructions

1. Analyze the job description to identify: required skills, preferred skills, industry, seniority level, key technologies.
2. Select the best experience framings from the profile. Use pre-written framings where they fit well, or generate NEW honest framings from raw_context when a better angle exists.
3. Select 2-3 most relevant projects. Exclude projects that don't add value for this specific role.
4. Reorder skills to prioritize what the JD asks for.
5. Write a tailored summary (2-3 sentences) that positions the candidate for THIS specific role.

## HONESTY RULES (CRITICAL)
- Only use experiences, projects, and skills from the profile
- NEVER fabricate metrics, titles, technologies, or company names
- You may reframe and emphasize differently, but every claim must trace to raw_context
- NEVER change: job titles at companies, dates, company names, degree, GPA
- Allowed: summary rewriting, bullet emphasis changes, skill reordering, project selection

## Output Format

Return a JSON object with this exact structure:

```json
{
  "resume": {
    "summary": "2-3 sentence tailored summary",
    "experience": [
      {
        "source": "kvbits",
        "framing_used": "ai_infrastructure",
        "title": "Job Title at Company",
        "company": "Company Name",
        "location": "Location",
        "period": "Date Range",
        "bullets": ["bullet 1", "bullet 2", "bullet 3", "bullet 4"]
      }
    ],
    "projects": [
      {
        "name": "Project Name",
        "bullets": ["bullet 1", "bullet 2"]
      }
    ],
    "skills": {
      "Category 1": ["skill1", "skill2"],
      "Category 2": ["skill3", "skill4"]
    },
    "certifications": ["Cert 1", "Cert 2"]
  },
  "decisions": {
    "angle": "Which framing angle was chosen",
    "projects_included": ["Project1", "Project2"],
    "projects_excluded": {"ProjectName": "reason for exclusion"},
    "skills_reordered": "Description of reordering",
    "certs_highlighted": ["Cert1", "Cert2"]
  }
}
```

Return ONLY the JSON. No markdown, no commentary.
```

- [ ] **Step 2: Create cover letter prompt template**

```markdown
<!-- prompts/cover_letter.md -->
You are an expert cover letter writer. Generate a tailored cover letter for the candidate.

## Candidate Profile Summary

{{profile_summary}}

## Job Details

Company: {{company}}
Title: {{title}}
Location: {{location}}

Description:
{{description}}

## Resume Angle Being Used

{{resume_angle}}

## Instructions

Write a professional cover letter (3-4 paragraphs):
1. Opening: Why this company and this role excite the candidate. Be specific to the company.
2. Body 1: Most relevant experience and how it maps to the role requirements.
3. Body 2: A specific project or achievement that demonstrates capability for this role.
4. Closing: Call to action, enthusiasm, availability.

Keep it under 350 words. Professional but genuine tone — not generic or overly formal.

## HONESTY RULES
- Only reference real experiences and projects from the profile
- Never claim skills or experience the candidate doesn't have

Return the cover letter as a JSON object:

```json
{
  "cover_letter": "Full cover letter text with proper paragraph breaks using \\n\\n"
}
```

Return ONLY the JSON. No markdown, no commentary.
```

- [ ] **Step 3: Commit**

```bash
git add prompts/
git commit -m "feat: add resume and cover letter prompt templates"
```

---

### Task 19: Resume Engine + PDF Renderer + Drive Uploader

**Files:**
- Create: `generation/__init__.py`
- Create: `generation/resume_engine.py`
- Create: `generation/pdf_renderer.py`
- Create: `generation/drive_uploader.py`
- Create: `templates/resume.html`
- Create: `tests/test_resume_engine.py`

- [ ] **Step 1: Write test for resume engine response parsing**

```python
# tests/test_resume_engine.py
import pytest
import json
from generation.resume_engine import ResumeEngine


MOCK_RESUME_RESPONSE = json.dumps({
    "resume": {
        "summary": "Cloud and AI infrastructure engineer...",
        "experience": [
            {
                "source": "kvbits",
                "framing_used": "ai_infrastructure",
                "title": "Junior Infrastructure Engineer",
                "company": "KV Bits",
                "location": "Chicago, IL",
                "period": "June 2024 - Present",
                "bullets": ["Built AWS infrastructure...", "Designed CI/CD..."],
            }
        ],
        "projects": [{"name": "DiaSense AI", "bullets": ["Deployed ML model..."]}],
        "skills": {"Cloud": ["AWS", "GCP"], "Containers": ["Docker", "K8s"]},
        "certifications": ["CompTIA Security+", "RHCSA"],
    },
    "decisions": {
        "angle": "AI Infrastructure",
        "projects_included": ["DiaSense AI"],
        "projects_excluded": {"VibeBox": "Not relevant"},
        "skills_reordered": "Cloud first",
        "certs_highlighted": ["GCP ACE"],
    },
})


class TestResumeEngine:
    def test_parse_resume_response(self):
        engine = ResumeEngine.__new__(ResumeEngine)
        result = engine._parse_response(MOCK_RESUME_RESPONSE)
        assert result is not None
        assert result["resume"]["summary"].startswith("Cloud")
        assert result["decisions"]["angle"] == "AI Infrastructure"

    def test_parse_handles_invalid_json(self):
        engine = ResumeEngine.__new__(ResumeEngine)
        result = engine._parse_response("not json")
        assert result is None
```

- [ ] **Step 2: Implement resume engine**

```python
# generation/__init__.py
"""Resume/cover letter generation and PDF rendering."""

# generation/resume_engine.py
"""Resume + cover letter generation via Claude Code CLI."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

import yaml

from config import YOUR_NAME, YOUR_EMAIL, YOUR_PHONE

logger = logging.getLogger(__name__)

RESUME_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "resume.md"
CL_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "cover_letter.md"


class ResumeEngine:
    def __init__(self, profile_path: str = "profile.yaml"):
        with open(profile_path) as f:
            self._profile_raw = f.read()
        self._profile = yaml.safe_load(self._profile_raw)

    def generate(
        self, company: str, title: str, location: str,
        description: str, source: str, screening_notes: str = "",
    ) -> dict | None:
        """Generate resume + cover letter for one job. Returns parsed dict or None."""
        resume_data = self._generate_resume(
            company, title, location, description, source, screening_notes,
        )
        if not resume_data:
            return None

        cover_letter_data = self._generate_cover_letter(
            company, title, location, description,
            resume_data.get("decisions", {}).get("angle", ""),
        )

        resume_data["cover_letter"] = cover_letter_data.get("cover_letter", "") if cover_letter_data else ""
        return resume_data

    def _generate_resume(
        self, company: str, title: str, location: str,
        description: str, source: str, screening_notes: str,
    ) -> dict | None:
        template = RESUME_PROMPT_PATH.read_text()
        prompt = (
            template
            .replace("{{profile_yaml}}", self._profile_raw)
            .replace("{{company}}", company)
            .replace("{{title}}", title)
            .replace("{{location}}", location)
            .replace("{{source}}", source)
            .replace("{{screening_notes}}", screening_notes)
            .replace("{{description}}", (description or "")[:4000])
        )
        output = self._invoke_claude(prompt)
        return self._parse_response(output) if output else None

    def _generate_cover_letter(
        self, company: str, title: str, location: str,
        description: str, resume_angle: str,
    ) -> dict | None:
        personal = self._profile.get("personal", {})
        profile_summary = f"Name: {personal.get('name', '')}\nVisa: {personal.get('visa', '')}"

        template = CL_PROMPT_PATH.read_text()
        prompt = (
            template
            .replace("{{profile_summary}}", profile_summary)
            .replace("{{company}}", company)
            .replace("{{title}}", title)
            .replace("{{location}}", location)
            .replace("{{description}}", (description or "")[:4000])
            .replace("{{resume_angle}}", resume_angle)
        )
        output = self._invoke_claude(prompt)
        return self._parse_response(output) if output else None

    def _invoke_claude(self, prompt: str) -> str | None:
        try:
            result = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "text"],
                capture_output=True, text=True, timeout=180,
            )
            if result.returncode != 0:
                logger.error(f"Claude CLI error: {result.stderr[:500]}")
                return None
            return result.stdout
        except subprocess.TimeoutExpired:
            logger.error("Claude CLI timed out during resume generation")
            return None
        except FileNotFoundError:
            logger.error("Claude CLI not found")
            return None

    def _parse_response(self, text: str) -> dict | None:
        text = text.strip()
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            text = match.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse response: {text[:200]}")
            return None
```

- [ ] **Step 3: Implement PDF renderer**

```python
# generation/pdf_renderer.py
"""HTML template -> PDF conversion via weasyprint."""
from __future__ import annotations

import logging
from pathlib import Path

from weasyprint import HTML

from config import YOUR_NAME, YOUR_EMAIL, YOUR_PHONE

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "resume.html"


def render_resume_pdf(resume_data: dict, output_path: Path) -> bool:
    """Render resume dict to PDF. Returns True on success."""
    try:
        template = TEMPLATE_PATH.read_text()
        html = _fill_template(template, resume_data)
        HTML(string=html).write_pdf(str(output_path))
        logger.info(f"Resume PDF written to {output_path}")
        return True
    except Exception as e:
        logger.error(f"PDF rendering failed: {e}")
        return False


def render_cover_letter_pdf(cover_letter_text: str, company: str, title: str, output_path: Path) -> bool:
    """Render cover letter text to PDF."""
    try:
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family: 'Georgia', serif; margin: 60px; font-size: 11pt; line-height: 1.6; color: #333; }}
  .header {{ margin-bottom: 30px; }}
  .header h1 {{ font-size: 14pt; margin: 0; }}
  .header p {{ margin: 2px 0; font-size: 10pt; color: #555; }}
  .content {{ margin-top: 20px; }}
  .content p {{ margin-bottom: 12px; text-align: justify; }}
</style></head><body>
<div class="header">
  <h1>{YOUR_NAME}</h1>
  <p>{YOUR_EMAIL} | {YOUR_PHONE}</p>
</div>
<div class="content">
  {"".join(f"<p>{para.strip()}</p>" for para in cover_letter_text.split(chr(10)+chr(10)) if para.strip())}
</div>
</body></html>"""
        HTML(string=html).write_pdf(str(output_path))
        logger.info(f"Cover letter PDF written to {output_path}")
        return True
    except Exception as e:
        logger.error(f"Cover letter PDF failed: {e}")
        return False


def _fill_template(template: str, resume_data: dict) -> str:
    """Fill the HTML template with resume data."""
    resume = resume_data.get("resume", {})

    # Build experience HTML
    exp_html = ""
    for exp in resume.get("experience", []):
        bullets = "".join(f"<li>{b}</li>" for b in exp.get("bullets", []))
        exp_html += f"""
        <div class="experience">
          <div class="job-header">
            <span class="job-title">{exp.get('title', '')} | {exp.get('company', '')}, {exp.get('location', '')}</span>
            <span class="dates">{exp.get('period', '')}</span>
          </div>
          <ul>{bullets}</ul>
        </div>"""

    # Build projects HTML
    proj_html = ""
    for proj in resume.get("projects", []):
        bullets = "".join(f"<li>{b}</li>" for b in proj.get("bullets", []))
        proj_html += f"""
        <div class="project">
          <strong>{proj.get('name', '')}</strong>
          <ul>{bullets}</ul>
        </div>"""

    # Build skills HTML
    skills_html = ""
    for category, items in resume.get("skills", {}).items():
        skills_html += f"<li><strong>{category}:</strong> {', '.join(items)}</li>"

    # Build certs HTML
    certs = resume.get("certifications", [])
    certs_html = "".join(f"<li>{c}</li>" for c in certs)

    return (
        template
        .replace("{{name}}", YOUR_NAME)
        .replace("{{email}}", YOUR_EMAIL)
        .replace("{{phone}}", YOUR_PHONE)
        .replace("{{summary}}", resume.get("summary", ""))
        .replace("{{experience}}", exp_html)
        .replace("{{projects}}", proj_html)
        .replace("{{skills}}", skills_html)
        .replace("{{certifications}}", certs_html)
    )
```

- [ ] **Step 4: Create resume HTML template**

```html
<!-- templates/resume.html -->
<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  @page { margin: 0.5in; size: letter; }
  body { font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 10pt; color: #222; margin: 0; line-height: 1.4; }
  h1 { font-size: 18pt; margin: 0 0 4px 0; text-align: center; }
  .contact { text-align: center; font-size: 9pt; color: #444; margin-bottom: 12px; }
  h2 { font-size: 11pt; border-bottom: 1.5px solid #222; padding-bottom: 2px; margin: 14px 0 6px 0; text-transform: uppercase; letter-spacing: 0.5px; }
  .summary { font-size: 10pt; margin-bottom: 8px; }
  .job-header { display: flex; justify-content: space-between; margin-bottom: 2px; }
  .job-title { font-weight: bold; font-size: 10pt; }
  .dates { font-size: 9pt; color: #555; white-space: nowrap; }
  ul { margin: 2px 0 8px 0; padding-left: 18px; }
  li { margin-bottom: 2px; font-size: 9.5pt; }
  .project strong { font-size: 10pt; }
  .skills li { margin-bottom: 1px; }
</style></head><body>

<h1>{{name}}</h1>
<div class="contact">{{email}} | {{phone}}</div>

<h2>Summary</h2>
<div class="summary">{{summary}}</div>

<h2>Work Experience</h2>
{{experience}}

<h2>Projects</h2>
{{projects}}

<h2>Skills</h2>
<ul class="skills">{{skills}}</ul>

<h2>Certifications</h2>
<ul>{{certifications}}</ul>

</body></html>
```

- [ ] **Step 5: Implement Drive uploader**

```python
# generation/drive_uploader.py
"""Upload generated PDFs to Google Drive."""
from __future__ import annotations

import logging
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials

from config import GOOGLE_SHEETS_CREDS_FILE, GOOGLE_DRIVE_FOLDER_ID

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]


class DriveUploader:
    def __init__(self):
        creds = Credentials.from_service_account_file(
            GOOGLE_SHEETS_CREDS_FILE, scopes=SCOPES
        )
        self.service = build("drive", "v3", credentials=creds)
        self.root_folder_id = GOOGLE_DRIVE_FOLDER_ID

    def upload_file(self, local_path: Path, drive_folder_id: str, filename: str) -> str:
        """Upload a file and return its web view link."""
        media = MediaFileUpload(str(local_path), mimetype="application/pdf")
        metadata = {
            "name": filename,
            "parents": [drive_folder_id],
        }
        file = self.service.files().create(
            body=metadata, media_body=media, fields="id, webViewLink"
        ).execute()

        link = file.get("webViewLink", "")
        logger.info(f"Uploaded {filename} to Drive: {link}")
        return link

    def get_or_create_folder(self, folder_name: str, parent_id: str | None = None) -> str:
        """Get or create a folder in Drive. Returns folder ID."""
        parent = parent_id or self.root_folder_id
        query = (
            f"name = '{folder_name}' and "
            f"'{parent}' in parents and "
            f"mimeType = 'application/vnd.google-apps.folder' and "
            f"trashed = false"
        )
        results = self.service.files().list(
            q=query, fields="files(id, name)", spaces="drive"
        ).execute()

        files = results.get("files", [])
        if files:
            return files[0]["id"]

        metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent],
        }
        folder = self.service.files().create(
            body=metadata, fields="id"
        ).execute()

        logger.info(f"Created Drive folder: {folder_name}")
        return folder["id"]
```

- [ ] **Step 6: Run tests and commit**

```bash
pytest tests/test_resume_engine.py -v
git add generation/ templates/ tests/test_resume_engine.py
git commit -m "feat: add resume/CL engine, PDF renderer, Drive uploader, and HTML template"
```

---

### Task 20: generate_materials.py

**Files:**
- Create: `generate_materials.py`

- [ ] **Step 1: Implement generate_materials.py**

```python
# generate_materials.py
"""
============================================================
  GENERATE MATERIALS — Resume + Cover Letter Automation
============================================================
  Reads Apply jobs from Daily tab, generates tailored
  resume + cover letter for each, uploads to Drive,
  moves to Applied tab.
============================================================
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date
from pathlib import Path

from config import DB_FILE, YOUR_NAME
from db.database import Database
from generation.resume_engine import ResumeEngine
from generation.pdf_renderer import render_resume_pdf, render_cover_letter_pdf
from generation.drive_uploader import DriveUploader
from models.job import ScreenedJob, ScreeningVerdict
from sheets.client import SheetsClient
from sheets import daily as daily_ops, applied as applied_ops

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    return text.lower().replace(" ", "-").replace(",", "").replace(".", "")[:50]


def main():
    db = Database(DB_FILE)
    db.initialize()

    sheets = SheetsClient()
    daily_ws = sheets.get_daily_sheet()
    applied_ws = sheets.get_applied_sheet()

    # Read Apply jobs from Daily tab
    apply_jobs = daily_ops.get_apply_jobs(daily_ws)
    if not apply_jobs:
        print("No jobs marked 'Apply' in Daily tab.")
        return

    print(f"\nGenerating materials for {len(apply_jobs)} jobs...\n")

    engine = ResumeEngine(profile_path="profile.yaml")
    uploader = DriveUploader()
    today = date.today().isoformat()

    for i, row in enumerate(apply_jobs, 1):
        company = row.get("Company", "")
        title = row.get("Job Title", "")
        location = row.get("Location", "")
        source = row.get("Source", "")
        confidence = row.get("Confidence", 3)
        reasoning = row.get("AI Reasoning", "")
        suggested_angle = row.get("Suggested Angle", "")
        apply_link = row.get("Apply Link", "")

        print(f"  [{i}/{len(apply_jobs)}] {company} — {title}")

        # Get full description from SQLite
        fingerprint = f"{company.strip().lower()}||{title.strip().lower()}"
        description = db.get_description_by_fingerprint(fingerprint) or ""

        # Generate resume + cover letter (fresh Claude invocation per job)
        result = engine.generate(
            company=company, title=title, location=location,
            description=description, source=source,
            screening_notes=f"Angle: {suggested_angle}. {reasoning}",
        )

        if not result:
            logger.error(f"  Failed to generate for {company} — {title}")
            continue

        # Create local output directory
        company_slug = slugify(company)
        role_slug = slugify(title)
        output_dir = Path("output") / company_slug / f"{today}_{role_slug}"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Render PDFs
        resume_path = output_dir / f"{YOUR_NAME.replace(' ', '_')}_Resume.pdf"
        cl_path = output_dir / f"{YOUR_NAME.replace(' ', '_')}_Cover_Letter.pdf"

        render_resume_pdf(result, resume_path)
        render_cover_letter_pdf(
            result.get("cover_letter", ""), company, title, cl_path,
        )

        # Save metadata
        metadata_path = output_dir / "_metadata.json"
        metadata_path.write_text(json.dumps({
            "job": {"company": company, "title": title, "source": source, "confidence": confidence},
            "decisions": result.get("decisions", {}),
            "generated_at": today,
        }, indent=2))

        # Upload to Google Drive
        company_folder = uploader.get_or_create_folder(company_slug)
        role_folder = uploader.get_or_create_folder(f"{today}_{role_slug}", company_folder)

        resume_link = uploader.upload_file(
            resume_path, role_folder, resume_path.name,
        )
        cl_link = uploader.upload_file(
            cl_path, role_folder, cl_path.name,
        )

        # Add to Applied tab
        screened = ScreenedJob(
            title=title, company=company, location=location,
            description="", url=apply_link, source=source,
            verdict=ScreeningVerdict.APPLY, confidence=int(confidence),
            reasoning=reasoning, suggested_angle=suggested_angle,
        )
        applied_ops.add_job(
            applied_ws, screened,
            resume_link=resume_link,
            cover_letter_link=cl_link,
            angle_used=result.get("decisions", {}).get("angle", suggested_angle),
        )

        # Save to feedback table
        db.save_feedback(
            job_fingerprint=fingerprint,
            company=company, title=title, source=source,
            screen_confidence=int(confidence),
            resume_angle=result.get("decisions", {}).get("angle", ""),
            date_applied=today,
        )

        print(f"    ✓ Resume + Cover Letter generated and uploaded")

    db.close()
    print(f"\nDone! {len(apply_jobs)} materials generated. Check the Applied tab.\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test compilation and commit**

```bash
python -m py_compile generate_materials.py
git add generate_materials.py
git commit -m "feat: add generate_materials.py — resume/CL generation, PDF, Drive upload, Applied tab"
```

---

## Phase 6: Feedback Loop

### Task 21: Feedback Sync + Report

**Files:**
- Create: `feedback_sync.py`
- Create: `feedback_report.py`

- [ ] **Step 1: Implement feedback_sync.py**

```python
# feedback_sync.py
"""Sync Applied tab outcomes to SQLite for feedback analysis."""
from __future__ import annotations

import logging
import sys

from config import DB_FILE
from db.database import Database
from sheets.client import SheetsClient
from sheets import applied as applied_ops

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    db = Database(DB_FILE)
    db.initialize()

    sheets = SheetsClient()
    applied_ws = sheets.get_applied_sheet()
    rows = applied_ops.get_all_applied(applied_ws)

    updated = 0
    for row in rows:
        company = row.get("Company", "")
        title = row.get("Job Title", "")
        status = row.get("Status", "")
        fingerprint = f"{company.strip().lower()}||{title.strip().lower()}"

        if status and status.lower() not in ("ready to apply", ""):
            outcome_map = {
                "applied": "applied",
                "phone screen": "phone_screen",
                "interview": "interview",
                "offer": "offer",
                "rejected": "rejected",
                "no response": "no_response",
            }
            outcome = outcome_map.get(status.lower(), status.lower())
            db.update_feedback_outcome(fingerprint, outcome)
            updated += 1

    db.close()
    print(f"Synced {updated} outcomes from Applied tab to SQLite.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Implement feedback_report.py**

```python
# feedback_report.py
"""Analyze application outcomes and generate recommendations."""
from __future__ import annotations

import sys

from config import DB_FILE
from db.database import Database

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    db = Database(DB_FILE)
    db.initialize()
    feedback = db.get_all_feedback()
    db.close()

    if not feedback:
        print("No feedback data yet. Apply to some jobs and update outcomes first.")
        return

    # Source quality
    source_stats: dict[str, dict] = {}
    angle_stats: dict[str, dict] = {}
    confidence_stats: dict[int, dict] = {}

    for row in feedback:
        source = row.get("source", "unknown")
        angle = row.get("resume_angle", "unknown")
        conf = row.get("screen_confidence", 0)
        outcome = row.get("outcome", "applied")

        is_callback = outcome in ("phone_screen", "interview", "offer")

        # Source
        if source not in source_stats:
            source_stats[source] = {"applied": 0, "callbacks": 0}
        source_stats[source]["applied"] += 1
        if is_callback:
            source_stats[source]["callbacks"] += 1

        # Angle
        if angle not in angle_stats:
            angle_stats[angle] = {"used": 0, "callbacks": 0}
        angle_stats[angle]["used"] += 1
        if is_callback:
            angle_stats[angle]["callbacks"] += 1

        # Confidence
        if conf not in confidence_stats:
            confidence_stats[conf] = {"applied": 0, "callbacks": 0}
        confidence_stats[conf]["applied"] += 1
        if is_callback:
            confidence_stats[conf]["callbacks"] += 1

    # Print reports
    print("\n" + "=" * 55)
    print("  FEEDBACK REPORT")
    print("=" * 55)

    print("\n  SOURCE QUALITY")
    print(f"  {'Source':<25} {'Applied':>8} {'Callbacks':>10} {'Rate':>8}")
    print("  " + "-" * 53)
    for source, stats in sorted(source_stats.items(), key=lambda x: x[1]["callbacks"], reverse=True):
        rate = (stats["callbacks"] / stats["applied"] * 100) if stats["applied"] else 0
        print(f"  {source:<25} {stats['applied']:>8} {stats['callbacks']:>10} {rate:>7.0f}%")

    print("\n  RESUME ANGLE EFFECTIVENESS")
    print(f"  {'Angle':<25} {'Used':>8} {'Callbacks':>10} {'Rate':>8}")
    print("  " + "-" * 53)
    for angle, stats in sorted(angle_stats.items(), key=lambda x: x[1]["callbacks"], reverse=True):
        rate = (stats["callbacks"] / stats["used"] * 100) if stats["used"] else 0
        print(f"  {angle:<25} {stats['used']:>8} {stats['callbacks']:>10} {rate:>7.0f}%")

    print("\n  SCREENING CALIBRATION")
    print(f"  {'Confidence':>10} {'Applied':>8} {'Callbacks':>10} {'Rate':>8}")
    print("  " + "-" * 38)
    for conf in sorted(confidence_stats.keys(), reverse=True):
        stats = confidence_stats[conf]
        rate = (stats["callbacks"] / stats["applied"] * 100) if stats["applied"] else 0
        print(f"  {conf:>10} {stats['applied']:>8} {stats['callbacks']:>10} {rate:>7.0f}%")

    print("\n" + "=" * 55 + "\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Commit**

```bash
git add feedback_sync.py feedback_report.py
git commit -m "feat: add feedback sync and report scripts"
```

---

## Phase 7: Polish

### Task 22: Update Profile Script

**Files:**
- Create: `update_profile.py`

- [ ] **Step 1: Implement update_profile.py**

```python
# update_profile.py
"""Interactive Q&A to add new experiences/projects to profile.yaml."""
from __future__ import annotations

import yaml
from pathlib import Path


def main():
    path = Path("profile.yaml")
    if not path.exists():
        print("profile.yaml not found.")
        return

    with open(path) as f:
        profile = yaml.safe_load(f)

    print("\nWhat would you like to add?")
    print("  1. New project")
    print("  2. New skill")
    print("  3. New certification/training")
    choice = input("\nChoice (1/2/3): ").strip()

    if choice == "1":
        name = input("Project name: ").strip()
        raw_context = input("Describe what you built (technologies, outcomes, metrics): ").strip()
        profile.setdefault("projects", []).append({
            "name": name,
            "raw_context": raw_context,
            "framings": {},
        })
        print(f"Added project: {name}")

    elif choice == "2":
        category = input("Skill category (e.g., cloud, ai_ml, programming): ").strip()
        skill = input("Skill name: ").strip()
        profile.setdefault("skills", {}).setdefault(category, []).append(skill)
        print(f"Added skill: {skill} under {category}")

    elif choice == "3":
        name = input("Certification/training name: ").strip()
        is_cert = input("Is this a certification (y) or training (n)? ").strip().lower()
        if is_cert == "y":
            issuer = input("Issuer: ").strip()
            status = input("Status (Active/Expired): ").strip()
            profile.setdefault("certifications", []).append({
                "name": name, "issuer": issuer, "status": status,
            })
        else:
            profile.setdefault("training", []).append(name)
        print(f"Added: {name}")

    with open(path, "w") as f:
        yaml.dump(profile, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print("profile.yaml updated.\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add update_profile.py
git commit -m "feat: add interactive profile update script"
```

---

### Task 23: Final Integration Test

- [ ] **Step 1: Verify all modules compile**

```bash
python -m py_compile config.py
python -m py_compile main.py
python -m py_compile generate_materials.py
python -m py_compile feedback_sync.py
python -m py_compile feedback_report.py
python -m py_compile update_profile.py
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v
```

- [ ] **Step 3: Verify .gitignore and commit any remaining files**

```bash
git status
git add -A
git commit -m "chore: final integration — all modules compile, tests pass"
```

---

## Summary

| Phase | Tasks | What it delivers |
|-------|-------|-----------------|
| 1: Foundation | Tasks 1-5 | Models, DB, config, profile vault — the data layer |
| 2: Scraper | Tasks 6-13 | 8+ source adapters with parallel orchestration |
| 3: Screening | Tasks 14-15 | Two-stage filter: regex + Claude CLI |
| 4: Sheets + Pipeline | Tasks 16-17 | Google Sheets integration + main.py orchestrator |
| 5: Resume Engine | Tasks 18-20 | Claude CLI generation + PDF + Drive + generate_materials.py |
| 6: Feedback | Task 21 | Outcome tracking + analysis reports |
| 7: Polish | Tasks 22-23 | Profile updater + integration verification |

**Total:** 23 tasks, ~100 steps. Each phase produces working, testable software.
