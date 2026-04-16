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
