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
