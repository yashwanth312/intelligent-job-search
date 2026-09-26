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

    def test_get_recently_audited_fingerprints_includes_all_stages(self, db):
        db.save_audit_entry(
            job_fingerprint="acme||sre", company="Acme", title="SRE",
            source="linkedin", stage="stage2_claude", verdict="APPLY",
            reason="good match", run_date="2026-09-01",
        )
        result = db.get_recently_audited_fingerprints(30)
        assert result == {"acme||sre"}
        assert "other||job" not in result

    def test_get_recently_audited_fingerprints_catches_long_lived_posting(self, db):
        """A job first seen 10 days ago (outside STALE_JOB_DAYS=5) but
        screened again yesterday must still count as 'known' — this is the
        30%-re-screen bug: known_fps used to key only on first-seen."""
        job = RawJob(
            title="SRE", company="Acme", location="Remote",
            url="https://example.com", source="linkedin",
        )
        db.save_jobs([job])
        db.conn.execute(
            "UPDATE jobs SET created_at = datetime('now', '-10 days') WHERE fingerprint = ?",
            (job.fingerprint,),
        )
        db.conn.commit()
        db.save_audit_entry(
            job_fingerprint=job.fingerprint, company="Acme", title="SRE",
            source="linkedin", stage="stage2_claude", verdict="APPLY",
            reason="still a good match", run_date="2026-09-07",
        )

        # First-seen-only view has long since forgotten it...
        assert job.fingerprint not in db.get_recent_fingerprints(5)
        # ...but the audit-history view still catches it.
        assert job.fingerprint in db.get_recently_audited_fingerprints(5)

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

    def test_update_description(self, db):
        job = RawJob(
            title="SRE", company="Meta", location="NYC",
            description=None,
            url="https://example.com/sre",
            source="linkedin",
        )
        db.save_jobs([job])
        assert db.get_description_by_fingerprint("meta||sre") is None

        db.update_description("meta||sre", "Updated job description text")
        assert db.get_description_by_fingerprint("meta||sre") == "Updated job description text"

    def test_get_url_by_fingerprint(self, db):
        job = RawJob(
            title="DevOps", company="Google", location="SF",
            url="https://example.com/devops",
            source="indeed",
        )
        db.save_jobs([job])
        assert db.get_url_by_fingerprint("google||devops") == "https://example.com/devops"
        assert db.get_url_by_fingerprint("unknown||job") is None


class TestClaudeUsage:
    def test_log_and_read_back(self, db):
        db.log_claude_usage(
            purpose="screening", label="Stage 2 screening", model="claude-haiku-4-5",
            input_tokens=1000, output_tokens=200,
            cache_creation_input_tokens=10, cache_read_input_tokens=500,
            cost_usd=0.05, duration_ms=1234, num_turns=1,
        )
        rows = db.get_claude_usage_rows()
        assert len(rows) == 1
        assert rows[0]["purpose"] == "screening"
        assert rows[0]["input_tokens"] == 1000
        assert rows[0]["cost_usd"] == 0.05

    def test_since_id_scopes_to_new_rows_only(self, db):
        db.log_claude_usage(purpose="screening", label="a", model="m", input_tokens=1)
        start_id = db.get_max_claude_usage_id()
        db.log_claude_usage(purpose="generation", label="b", model="m", input_tokens=2)
        db.log_claude_usage(purpose="generation", label="c", model="m", input_tokens=3)

        since = db.get_claude_usage_since_id(start_id)
        assert len(since) == 2
        assert {r["purpose"] for r in since} == {"generation"}

    def test_get_max_usage_id_zero_when_empty(self, db):
        assert db.get_max_claude_usage_id() == 0

    def test_rows_since_timestamp_filter(self, db):
        db.log_claude_usage(purpose="verification", label="v", model="m", input_tokens=1)
        far_future = "2999-01-01 00:00:00"
        assert db.get_claude_usage_rows(since=far_future) == []
        assert len(db.get_claude_usage_rows()) == 1


class TestFeedbackProjectColumns:
    def test_save_feedback_records_projects_and_admission(self, db):
        db.save_feedback(
            job_fingerprint="acme||sysadmin", company="Acme", title="Sysadmin",
            source="linkedin", screen_confidence=4, resume_angle="devops",
            date_applied="2026-09-26", projects_used=["hybridid", "restorepoint", "fleetforge"],
            project_coverage=0.82, admission="it_identity",
        )
        row = db.get_all_feedback()[0]
        assert row["projects_used"] == '["hybridid", "restorepoint", "fleetforge"]'
        assert row["project_coverage"] == 0.82
        assert row["admission"] == "it_identity"

    def test_old_feedback_table_is_migrated(self, tmp_path):
        import sqlite3
        path = tmp_path / "old.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE feedback (id INTEGER PRIMARY KEY, job_fingerprint TEXT NOT NULL)")
        conn.commit()
        conn.close()

        database = Database(str(path))
        database.initialize()
        cols = {r["name"] for r in database.conn.execute("PRAGMA table_info(feedback)")}
        database.close()
        assert {"projects_used", "project_coverage", "admission"} <= cols
