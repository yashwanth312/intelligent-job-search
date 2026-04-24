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
