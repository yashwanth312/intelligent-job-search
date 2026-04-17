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

    def test_passes_empty_description_if_title_matches(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(description=None))
        assert result.passed is True
        assert "no description" in result.reason.lower()

    def test_rejects_empty_description_with_bad_title(self):
        f = Stage1Filter()
        result = f.filter_job(make_job(title="Marketing Coordinator", description=None))
        assert result.passed is False

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
