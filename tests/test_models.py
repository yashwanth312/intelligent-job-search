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
