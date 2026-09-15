"""Tests for the deterministic parts of the resume verifier (keyword coverage,
feedback formatting, response parsing). The Claude CLI call itself is not
unit-tested here — only the pure logic around it."""
from generation.verifier import (
    ResumeVerifier,
    keyword_coverage,
    format_feedback,
    _resume_text,
)


def _resume(**over) -> dict:
    base = {
        "resume": {
            "summary": "Cloud engineer with AWS and Terraform experience.",
            "experience": [
                {"bullets": ["Built **CI/CD** pipelines with Jenkins and Docker"]}
            ],
            "projects": [{"bullets": ["Provisioned a VPC with Terraform"]}],
            "skills": {"Cloud": ["AWS", "Kubernetes"], "Security": ["IAM", "SIEM"]},
        }
    }
    base["resume"].update(over)
    return base


class TestKeywordCoverage:
    def test_full_coverage(self):
        cov, missing = keyword_coverage(_resume(), ["aws", "terraform", "jenkins"])
        assert cov == 1.0
        assert missing == []

    def test_partial_coverage_and_missing(self):
        cov, missing = keyword_coverage(_resume(), ["aws", "gcp", "azure", "iam"])
        # aws + iam present, gcp + azure missing -> 2/4
        assert cov == 0.5
        assert set(missing) == {"gcp", "azure"}

    def test_no_keywords_is_full(self):
        cov, missing = keyword_coverage(_resume(), [])
        assert cov == 1.0
        assert missing == []

    def test_bold_markers_do_not_break_match(self):
        # "ci/cd" appears only as **CI/CD** in a bullet; markers must be stripped
        cov, missing = keyword_coverage(_resume(), ["ci/cd"])
        assert cov == 1.0
        assert missing == []


class TestResumeText:
    def test_flattens_all_sections_lowercased(self):
        text = _resume_text(_resume())
        for token in ("aws", "terraform", "jenkins", "kubernetes", "iam", "siem", "vpc"):
            assert token in text
        assert "**" not in text  # bold markers stripped


class TestFormatFeedback:
    def test_includes_score_gaps_fixes_flags(self):
        vr = {
            "interview_likelihood": 62,
            "gaps": ["No evidence of Kubernetes in production"],
            "fixes": ["Lead skills with Kubernetes + EKS, back it with the DiaSense bullet"],
            "red_flags": ["Summary names the company"],
        }
        fb = format_feedback(vr)
        assert "62/100" in fb
        assert "Kubernetes in production" in fb
        assert "DiaSense" in fb
        assert "names the company" in fb

    def test_empty_sections_omitted(self):
        fb = format_feedback({"interview_likelihood": 90})
        assert "90/100" in fb
        assert "Gaps" not in fb and "fixes" not in fb.lower()


class TestParseResponse:
    def test_parses_fenced_json(self):
        v = ResumeVerifier()
        raw = '```json\n{"interview_likelihood": 88, "verdict": "ship"}\n```'
        out = v._parse_response(raw)
        assert out["interview_likelihood"] == 88
        assert out["verdict"] == "ship"

    def test_rejects_missing_score_key(self):
        v = ResumeVerifier()
        assert v._parse_response('{"verdict": "ship"}') is None

    def test_rejects_non_json(self):
        v = ResumeVerifier()
        assert v._parse_response("the resume looks great!") is None
