"""Tests for rescreen._row_to_raw_job reconstruction logic."""
from unittest.mock import MagicMock


def test_row_to_raw_job_with_description():
    from rescreen import _row_to_raw_job

    row = {
        "Company": "Acme Corp",
        "Job Title": "Cloud Engineer",
        "Location": "Chicago, IL",
        "Source": "greenhouse-acme",
        "Apply Link": "https://example.com/job/1",
    }
    db = MagicMock()
    db.get_job_by_fingerprint.return_value = {
        "description": "We need a cloud engineer with AWS skills."
    }

    job = _row_to_raw_job(row, db)

    assert job.company == "Acme Corp"
    assert job.title == "Cloud Engineer"
    assert job.location == "Chicago, IL"
    assert job.source == "greenhouse-acme"
    assert job.url == "https://example.com/job/1"
    assert job.description == "We need a cloud engineer with AWS skills."
    assert job.fingerprint == "acme corp||cloud engineer"
    assert job.salary_min is None
    assert job.salary_max is None
    assert job.posted_at is None
    db.get_job_by_fingerprint.assert_called_once_with("acme corp||cloud engineer")


def test_row_to_raw_job_no_db_record():
    from rescreen import _row_to_raw_job

    row = {
        "Company": "Beta Inc",
        "Job Title": "DevOps Engineer",
        "Location": "Remote",
        "Source": "lever-beta",
        "Apply Link": "https://example.com/job/2",
    }
    db = MagicMock()
    db.get_job_by_fingerprint.return_value = None

    job = _row_to_raw_job(row, db)

    assert job.description is None
    assert job.company == "Beta Inc"
    assert job.title == "DevOps Engineer"
    assert job.location == "Remote"
    assert job.source == "lever-beta"
    assert job.url == "https://example.com/job/2"


def test_row_to_raw_job_db_record_empty_description():
    from rescreen import _row_to_raw_job

    row = {
        "Company": "Gamma LLC",
        "Job Title": "SRE",
        "Location": "New York, NY",
        "Source": "ashby-gamma",
        "Apply Link": "https://example.com/job/3",
    }
    db = MagicMock()
    db.get_job_by_fingerprint.return_value = {"description": ""}

    job = _row_to_raw_job(row, db)

    assert job.description is None


def test_row_to_raw_job_missing_optional_columns():
    """Sheet rows may omit optional columns — should not raise."""
    from rescreen import _row_to_raw_job

    row = {
        "Company": "Delta Co",
        "Job Title": "Platform Engineer",
        # Location, Source, Apply Link intentionally absent
    }
    db = MagicMock()
    db.get_job_by_fingerprint.return_value = None

    job = _row_to_raw_job(row, db)

    assert job.company == "Delta Co"
    assert job.title == "Platform Engineer"
    assert job.location == ""
    assert job.source == ""
    assert job.url == ""
