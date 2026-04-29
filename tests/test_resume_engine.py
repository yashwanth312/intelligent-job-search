import pytest
import json
from generation.resume_engine import ResumeEngine


MOCK_COMBINED_RESPONSE = json.dumps({
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
    "cover_letter": "Dear Hiring Manager,\n\nI'm excited to apply...\n\nSincerely,\nYash",
})


class TestResumeEngine:
    def test_parse_combined_response(self):
        engine = ResumeEngine.__new__(ResumeEngine)
        result = engine._parse_response(MOCK_COMBINED_RESPONSE)
        assert result is not None
        assert result["resume"]["summary"].startswith("Cloud")
        assert result["decisions"]["angle"] == "AI Infrastructure"
        assert "I'm excited to apply" in result["cover_letter"]

    def test_parse_handles_invalid_json(self):
        engine = ResumeEngine.__new__(ResumeEngine)
        result = engine._parse_response("not json")
        assert result is None

    def test_parse_strips_markdown_fences(self):
        engine = ResumeEngine.__new__(ResumeEngine)
        wrapped = f"```json\n{MOCK_COMBINED_RESPONSE}\n```"
        result = engine._parse_response(wrapped)
        assert result is not None
        assert result["resume"]["summary"].startswith("Cloud")

    def test_parse_rejects_response_without_resume_key(self):
        engine = ResumeEngine.__new__(ResumeEngine)
        result = engine._parse_response('{"only": "noise"}')
        assert result is None

    def test_parse_defaults_missing_cover_letter_and_decisions(self):
        engine = ResumeEngine.__new__(ResumeEngine)
        minimal = json.dumps({"resume": {"summary": "x", "experience": [], "projects": [], "skills": {}, "certifications": []}})
        result = engine._parse_response(minimal)
        assert result is not None
        assert result["cover_letter"] == ""
        assert result["decisions"] == {}
