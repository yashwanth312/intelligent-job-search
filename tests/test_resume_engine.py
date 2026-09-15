import pytest
import json
from unittest.mock import patch
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


class TestResumeEnginePromptSplit:
    """generate() splits application_materials.md into a cached system prompt
    (profile + static instructions) and a small per-job dynamic prompt."""

    def _engine(self, profile_yaml_path):
        return ResumeEngine(profile_path=str(profile_yaml_path))

    def test_system_prompt_contains_profile_not_job_fields(self, tmp_path):
        profile = tmp_path / "profile.yaml"
        profile.write_text("name: Test Candidate\n", encoding="utf-8")
        engine = self._engine(profile)
        sys_prompt = engine._build_system_prompt()

        assert "Test Candidate" in sys_prompt
        assert "{{profile_yaml}}" not in sys_prompt
        assert "{{company}}" not in sys_prompt
        assert "LOCKED CONSTANTS" in sys_prompt

    def test_system_prompt_is_memoized(self, tmp_path):
        profile = tmp_path / "profile.yaml"
        profile.write_text("name: Test Candidate\n", encoding="utf-8")
        engine = self._engine(profile)
        first = engine._build_system_prompt()
        second = engine._build_system_prompt()
        assert first is second

    def test_generate_calls_run_claude_with_system_prompt_and_thinking_off(self, tmp_path):
        profile = tmp_path / "profile.yaml"
        profile.write_text("name: Test Candidate\n", encoding="utf-8")
        engine = self._engine(profile)

        with patch("generation.resume_engine.run_claude", return_value=None) as mock_run:
            engine.generate(
                company="Acme", title="DevOps Engineer", location="Remote",
                description="Do infra things", source="linkedin",
            )

        assert mock_run.call_count == 1
        _args, kwargs = mock_run.call_args
        assert kwargs["disable_thinking"] is True
        assert "Test Candidate" in kwargs["system_prompt"]
        dynamic_prompt = mock_run.call_args.args[0]
        assert "Acme" in dynamic_prompt
        assert "DevOps Engineer" in dynamic_prompt
        assert "Test Candidate" not in dynamic_prompt
        assert "LOCKED CONSTANTS" not in dynamic_prompt
