"""A newcomer's first steps: copy profile.example.yaml, run the pipeline pieces.

Everything here uses the shipped example profile exactly as a fresh clone
would, with the Claude CLI call mocked out.
"""
import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def profile_path(tmp_path):
    dest = tmp_path / "profile.yaml"
    shutil.copy(ROOT / "profile.example.yaml", dest)
    return dest


def test_example_profile_validates_against_the_model(profile_path):
    from models.profile import Profile
    profile = Profile(**yaml.safe_load(profile_path.read_text(encoding="utf-8")))
    assert profile.personal.name == "Jane Doe"
    assert len(profile.experiences) == 2
    assert profile.experiences[0].locked_title == "Software Engineer"
    assert len(profile.projects) == 2
    assert profile.portfolio_catalog == []


def test_example_project_skill_tags_exist_in_the_taxonomy(profile_path):
    from generation.skill_taxonomy import SKILLS
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    for project in data["projects"]:
        for tier in ("core", "supporting", "touch"):
            for tag in project["skills"][tier]:
                assert tag in SKILLS, (project["name"], tag)


def test_stage2_prompt_uses_the_profile_and_fills_every_placeholder(profile_path):
    from screening.stage2 import Stage2Screen
    prompt = Stage2Screen(profile_path=str(profile_path))._build_system_prompt()
    assert "Jane Doe" in prompt
    assert "0-3 years / junior-to-mid" in prompt          # config.TARGET_LEVEL
    assert "{{" not in prompt


def test_resume_prompt_is_built_from_the_newcomers_profile(profile_path):
    from generation.resume_engine import ResumeEngine
    prompt = ResumeEngine(profile_path=str(profile_path))._build_system_prompt()
    assert "Jane Doe" in prompt and "Acme Corp" in prompt
    assert "F1 OPT" not in prompt
    # Projects are rendered per job, never in the cached system prompt.
    assert "TaskFlow" not in prompt
    assert "{{profile_yaml}}" not in prompt


def test_generation_selects_the_best_projects_and_sends_only_those(profile_path):
    from generation.resume_engine import ResumeEngine
    engine = ResumeEngine(profile_path=str(profile_path))
    reply = json.dumps({"resume": {"personal": {"location": "Austin, TX"}, "summary": "s",
                                   "experience": [], "education": [], "skills": {}},
                        "decisions": {}, "cover_letter": "Dear Acme Hiring Team,"})
    with patch("generation.resume_engine.run_claude", return_value=reply) as run:
        result = engine.generate(
            company="Acme", title="Cloud Engineer", location="Remote", source="linkedin",
            description="Terraform and AWS Lambda cost optimization (FinOps) with Python.",
        )
    assert result is not None
    sent = run.call_args.args[0]
    assert "CloudWatchDog" in sent            # best match for this JD
    assert "{{" not in sent
    assert result["_project_selection"]["projects"][0]["name"] == "CloudWatchDog"


def test_generation_works_with_fewer_than_three_projects(profile_path):
    """Two projects, no catalog: the scorer must not crash or invent a third."""
    from generation.resume_engine import ResumeEngine
    sel = ResumeEngine(profile_path=str(profile_path)).select_projects("Software Engineer", "Python APIs")
    assert 1 <= len(sel.names) <= 2


def test_rendered_resume_has_no_template_leftovers(profile_path, tmp_path):
    from generation.pdf_renderer import render_resume_pdf
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    exp = data["experiences"][0]
    resume = {
        "personal": {"location": data["personal"]["location"]},
        "summary": "Backend engineer who ships and operates Python services.",
        "experience": [{"title": exp["locked_title"], "company": exp["company"],
                        "location": exp["location"], "period": exp["period"],
                        "bullets": exp["framings"]["backend"]["bullets"]}],
        "education": data["education"],
        "skills": data["skills"],
        "certifications": data["certifications"],
        "projects": [{"name": "TaskFlow", "bullets": data["projects"][0]["framings"]["backend"]["bullets"]}],
    }
    out = tmp_path / "resume.pdf"
    render_resume_pdf(resume, out)
    produced = out if out.exists() else out.with_suffix(".html")
    assert produced.exists(), "neither a PDF nor the HTML fallback was written"
    if produced.suffix == ".html":
        assert "{{" not in produced.read_text(encoding="utf-8")


def test_check_setup_accepts_the_example_profile(profile_path, monkeypatch):
    import scripts.check_setup as cs
    monkeypatch.setattr(cs, "ROOT", profile_path.parent)
    cs._results.clear()
    cs.check_profile()
    levels = {name: level for level, name, _ in cs._results}
    assert levels["profile.yaml schema"] == "PASS"
    assert levels["project skill tags"] == "PASS"
    assert levels["prompts build from your profile"] == "PASS"
    assert levels["profile.yaml placeholders"] == "WARN"      # still the example text
    cs._results.clear()


def test_check_setup_fails_on_a_missing_or_broken_profile(tmp_path, monkeypatch):
    import scripts.check_setup as cs
    monkeypatch.setattr(cs, "ROOT", tmp_path)
    cs._results.clear()
    cs.check_profile()
    assert cs._results[0][0] == "FAIL"
    (tmp_path / "profile.yaml").write_text("personal: {name: x}\n", encoding="utf-8")
    cs._results.clear()
    cs.check_profile()
    assert cs._results[0][:2] == ("FAIL", "profile.yaml schema")
    cs._results.clear()


def test_materials_paths_follow_the_configured_root(monkeypatch):
    import generate_materials as gm
    target = gm.REPO_ROOT / "output" / "acme" / "r.pdf"
    monkeypatch.setattr(gm, "USER_LAPTOP_REPO_PATH", r"D:\work\jobs")
    assert gm.laptop_materials_path(target) == r"D:\work\jobs\output\acme\r.pdf"
    monkeypatch.setattr(gm, "USER_LAPTOP_REPO_PATH", "/home/jane/jobs/")
    assert gm.laptop_materials_path(target) == "/home/jane/jobs/output/acme/r.pdf"
