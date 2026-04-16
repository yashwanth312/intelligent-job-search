import pytest
import json
from screening.stage2 import Stage2Screen


MOCK_CLAUDE_OUTPUT = json.dumps([
    {
        "fingerprint": "google||cloud engineer",
        "verdict": "APPLY",
        "confidence": 4,
        "reasoning": "Strong match: AWS + K8s experience aligns well",
        "match_signals": ["AWS", "Kubernetes", "Terraform"],
        "risk_flags": [],
        "suggested_angle": "AI Infrastructure",
    }
])


class TestStage2Screen:
    def test_parse_claude_response(self):
        screen = Stage2Screen(profile_path="profile.yaml")
        results = screen._parse_response(MOCK_CLAUDE_OUTPUT)
        assert len(results) == 1
        assert results[0]["verdict"] == "APPLY"
        assert results[0]["confidence"] == 4

    def test_parse_handles_invalid_json(self):
        screen = Stage2Screen(profile_path="profile.yaml")
        results = screen._parse_response("not valid json at all")
        assert results == []

    def test_parse_handles_json_in_markdown(self):
        screen = Stage2Screen(profile_path="profile.yaml")
        wrapped = f"```json\n{MOCK_CLAUDE_OUTPUT}\n```"
        results = screen._parse_response(wrapped)
        assert len(results) == 1
