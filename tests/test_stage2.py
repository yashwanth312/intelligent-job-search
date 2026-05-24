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


def test_default_apply_does_not_inject_no_h1b_history_flag():
    """no_h1b_history was a risk flag; sponsorship now has its own column."""
    from models.job import RawJob
    from screening.stage2 import Stage2Screen

    job = RawJob(
        title="Cloud Engineer",
        company="Acme",
        location="Remote",
        url="https://example.com",
        source="linkedin",
        h1b_sponsor_verified=False,  # would have triggered the flag previously
    )
    screened = Stage2Screen()._default_apply(job)
    assert "no_h1b_history" not in screened.risk_flags


def test_default_maybe_does_not_inject_no_h1b_history_flag():
    from models.job import RawJob
    from screening.stage2 import Stage2Screen

    job = RawJob(
        title="Cloud Engineer",
        company="Acme",
        location="Remote",
        url="https://example.com",
        source="linkedin",
        h1b_sponsor_verified=False,
    )
    screened = Stage2Screen()._default_maybe(job)
    assert "no_h1b_history" not in screened.risk_flags


def test_screen_batch_warns_on_partial_response():
    """When Claude returns fewer jobs than submitted, a WARNING is logged naming the missing jobs."""
    from unittest.mock import patch
    from models.job import RawJob

    jobs = [
        RawJob(title="Cloud Engineer", company="Acme", location="Remote",
               url="https://a.com", source="linkedin"),
        RawJob(title="DevOps Engineer", company="Beta", location="Remote",
               url="https://b.com", source="linkedin"),
    ]
    # Only the first job is returned by Claude
    partial = [{
        "fingerprint": jobs[0].fingerprint,
        "verdict": "APPLY", "confidence": 4, "reasoning": "Good",
        "match_signals": [], "risk_flags": [], "suggested_angle": "",
    }]

    screen = Stage2Screen(profile_path="profile.yaml")
    with patch.object(screen, "_screen_one_batch", return_value=partial), \
         patch.object(screen, "_load_profile_summary", return_value="summary"), \
         patch("screening.stage2.logger") as mock_log:
        result = screen.screen_batch(jobs)

    assert mock_log.warning.call_count >= 1
    msg = mock_log.warning.call_args[0][0]
    assert "1/2 returned" in msg
    assert "DevOps Engineer" in msg
    assert len(result) == 2  # both jobs still in output (one APPLY, one MAYBE)
