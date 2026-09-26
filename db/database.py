"""SQLite database connection and operations."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
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

            CREATE TABLE IF NOT EXISTS h1b_sponsor_cache (
                company_key  TEXT PRIMARY KEY,
                company_raw  TEXT NOT NULL,
                verified     INTEGER NOT NULL,
                checked_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS claude_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT (datetime('now')),
                purpose TEXT NOT NULL,
                label TEXT,
                model TEXT,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cache_creation_input_tokens INTEGER DEFAULT 0,
                cache_read_input_tokens INTEGER DEFAULT 0,
                cost_usd REAL,
                duration_ms INTEGER,
                num_turns INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint);
            CREATE INDEX IF NOT EXISTS idx_jobs_created_fp ON jobs(created_at, fingerprint);
            CREATE INDEX IF NOT EXISTS idx_audit_run_date ON screening_audit(run_date);
            CREATE INDEX IF NOT EXISTS idx_audit_created_at ON screening_audit(created_at, job_fingerprint);
            CREATE INDEX IF NOT EXISTS idx_feedback_fingerprint ON feedback(job_fingerprint);
            CREATE INDEX IF NOT EXISTS idx_claude_usage_purpose ON claude_usage(purpose);
        """)
        self._add_missing_columns("feedback", {
            # JSON list of project ids the resume carried (generation.project_scorer)
            "projects_used": "TEXT",
            "project_coverage": "REAL",
            # which Stage 1 title family admitted the job: core | it_identity
            "admission": "TEXT",
        })

    def _add_missing_columns(self, table: str, columns: dict[str, str]) -> None:
        existing = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
        for name, sql_type in columns.items():
            if name not in existing:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
        self.conn.commit()

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

    def get_recent_fingerprints(self, days: int) -> set[str]:
        """Return fingerprints of all jobs seen in the last `days` days.

        Used to dedupe across runs so we don't re-process the same listings
        day after day. Uses `created_at` (when we first saw it), not `scraped_at`,
        since a job's scraped_at is refreshed whenever it re-scrapes.
        """
        cursor = self.conn.execute(
            "SELECT fingerprint FROM jobs WHERE created_at >= datetime('now', ?)",
            (f"-{int(days)} days",),
        )
        return {row["fingerprint"] for row in cursor.fetchall()}

    def get_recently_audited_fingerprints(self, days: int) -> set[str]:
        """Return fingerprints of every job that appeared in ANY screening_audit
        row (stage1/h1b/stage2, any verdict) in the last `days` days.

        Unlike `get_recent_fingerprints` (keyed on `jobs.created_at`, i.e. when
        a fingerprint was FIRST seen), this is keyed on when it was last
        actually screened. A long-lived posting from a prefiltered source
        (LinkedIn/Indeed/Google) can resurface as "fresh" every day forever;
        without this, it falls out of the first-seen window after
        STALE_JOB_DAYS and gets silently re-screened by Stage 2 daily even
        though we already have a verdict for it. Union this with
        `get_recent_fingerprints` when deciding what's safe to skip re-scraping.
        """
        cursor = self.conn.execute(
            "SELECT DISTINCT job_fingerprint FROM screening_audit WHERE created_at >= datetime('now', ?)",
            (f"-{int(days)} days",),
        )
        return {row["job_fingerprint"] for row in cursor.fetchall()}

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
        date_applied: str, projects_used: list[str] | None = None,
        project_coverage: float | None = None, admission: str | None = None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO feedback
            (job_fingerprint, company, title, source, screen_confidence, resume_angle,
             date_applied, projects_used, project_coverage, admission)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_fingerprint, company, title, source, screen_confidence, resume_angle,
             date_applied, json.dumps(projects_used) if projects_used is not None else None,
             project_coverage, admission),
        )
        self.conn.commit()

    def update_feedback_outcome(self, job_fingerprint: str, outcome: str) -> int:
        """Set the outcome on every feedback row for this job; returns rows matched."""
        cur = self.conn.execute(
            """UPDATE feedback SET outcome = ?, updated_at = datetime('now')
            WHERE job_fingerprint = ?""",
            (outcome, job_fingerprint),
        )
        self.conn.commit()
        return cur.rowcount

    def get_all_feedback(self) -> list[dict]:
        cursor = self.conn.execute("SELECT * FROM feedback ORDER BY date_applied DESC")
        return [dict(row) for row in cursor.fetchall()]

    def get_description_by_fingerprint(self, fingerprint: str) -> str | None:
        cursor = self.conn.execute(
            "SELECT description FROM jobs WHERE fingerprint = ?", (fingerprint,)
        )
        row = cursor.fetchone()
        return row["description"] if row else None

    def update_description(self, fingerprint: str, description: str) -> None:
        """Update the description for a job identified by fingerprint."""
        self.conn.execute(
            "UPDATE jobs SET description = ? WHERE fingerprint = ?",
            (description, fingerprint),
        )
        self.conn.commit()

    def get_url_by_fingerprint(self, fingerprint: str) -> str | None:
        """Get the URL for a job identified by fingerprint."""
        cursor = self.conn.execute(
            "SELECT url FROM jobs WHERE fingerprint = ?", (fingerprint,)
        )
        row = cursor.fetchone()
        return row["url"] if row else None

    def get_h1b_cache(self, company_key: str) -> bool | None:
        """Return cached verified bool if fresh (within TTL), else None.

        Positives and negatives get different TTLs on purpose. A cached True is
        a fact about an employer's filing history and barely decays. A cached
        False is only ever "none of the query forms we tried matched anything on
        h1bdata.info" — which is also what a renamed entity, a decorated job-board
        company string, or a transient site hiccup looks like. Expiring negatives
        sooner means a wrong one self-heals in days instead of silently dropping
        every posting from that employer for a month.
        """
        from config import H1B_CACHE_TTL_DAYS, H1B_NEGATIVE_CACHE_TTL_DAYS
        row = self.conn.execute(
            "SELECT verified, checked_at FROM h1b_sponsor_cache WHERE company_key = ?",
            (company_key,),
        ).fetchone()
        if row is None:
            return None
        checked = datetime.fromisoformat(row["checked_at"])
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - checked).days
        verified = bool(row["verified"])
        ttl = H1B_CACHE_TTL_DAYS if verified else H1B_NEGATIVE_CACHE_TTL_DAYS
        if age_days >= ttl:
            return None
        return verified

    def get_verified_sponsor_keys(self) -> set[str]:
        """Return every company_key currently cached as a confirmed sponsor.

        Used to let a decorated company string ("Amazon Web Services (AWS)",
        "NVIDIA AI") inherit the verdict already earned by its parent brand
        instead of being scraped as an unrelated employer and dropped.
        """
        from config import H1B_CACHE_TTL_DAYS
        cursor = self.conn.execute(
            "SELECT company_key FROM h1b_sponsor_cache "
            "WHERE verified = 1 AND checked_at >= datetime('now', ?)",
            (f"-{int(H1B_CACHE_TTL_DAYS)} days",),
        )
        return {row["company_key"] for row in cursor.fetchall()}

    def set_h1b_cache(self, company_key: str, company_raw: str, verified: bool) -> None:
        """Upsert a sponsor check result. Only call with definitive True/False, not None."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT OR REPLACE INTO h1b_sponsor_cache
               (company_key, company_raw, verified, checked_at)
               VALUES (?, ?, ?, ?)""",
            (company_key, company_raw, int(verified), now),
        )
        self.conn.commit()

    def log_claude_usage(
        self, *, purpose: str, label: str, model: str,
        input_tokens: int = 0, output_tokens: int = 0,
        cache_creation_input_tokens: int = 0, cache_read_input_tokens: int = 0,
        cost_usd: float | None = None, duration_ms: int | None = None,
        num_turns: int | None = None,
    ) -> None:
        """Record one Claude CLI call's usage. `purpose` is a free-form tag
        ("screening", "generation", "verification", ...) used to break down
        cumulative usage by what the call was for."""
        self.conn.execute(
            """INSERT INTO claude_usage
            (purpose, label, model, input_tokens, output_tokens,
             cache_creation_input_tokens, cache_read_input_tokens,
             cost_usd, duration_ms, num_turns)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (purpose, label, model, input_tokens, output_tokens,
             cache_creation_input_tokens, cache_read_input_tokens,
             cost_usd, duration_ms, num_turns),
        )
        self.conn.commit()

    def get_max_claude_usage_id(self) -> int:
        row = self.conn.execute("SELECT MAX(id) AS m FROM claude_usage").fetchone()
        return row["m"] or 0

    def get_claude_usage_since_id(self, min_id: int) -> list[dict]:
        """Rows logged after `min_id` — pair with get_max_claude_usage_id() taken
        before a run starts to scope usage to that run, without relying on
        clock-format matching against SQLite's datetime('now')."""
        cursor = self.conn.execute(
            "SELECT * FROM claude_usage WHERE id > ? ORDER BY id", (min_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_claude_usage_rows(self, since: str | None = None) -> list[dict]:
        """All usage rows, optionally restricted to ts >= `since`
        (format 'YYYY-MM-DD HH:MM:SS', matching SQLite's datetime('now'))."""
        if since:
            cursor = self.conn.execute(
                "SELECT * FROM claude_usage WHERE ts >= ? ORDER BY ts", (since,)
            )
        else:
            cursor = self.conn.execute("SELECT * FROM claude_usage ORDER BY ts")
        return [dict(row) for row in cursor.fetchall()]
