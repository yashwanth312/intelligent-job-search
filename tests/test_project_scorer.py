from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from generation.portfolio import (
    PortfolioProject, catalog_summary, load_portfolio, parse_spec, strip_top_level_keys,
)
from generation.project_scorer import ProjectScorer, _line_weights
from generation.skill_taxonomy import SKILLS, extract

SPECS = Path(__file__).resolve().parent.parent / "docs" / "projects"


@pytest.fixture(scope="module")
def profile_path(tmp_path_factory):
    """A stand-in profile.yaml (the real one is gitignored personal data):
    one built project plus pointers to every committed catalog spec."""
    catalog = []
    for spec in sorted(SPECS.glob("[0-9][0-9]-*.md")):
        meta, _ = parse_spec(spec)
        catalog.append({"id": meta["id"], "name": meta["name"], "spec": str(spec)})
    data = {
        "personal": {"name": "Test Candidate", "location": "Chicago, IL"},
        "projects": [{
            "name": "Intelligent Job Search", "id": "intelligent-job-search",
            "raw_context": "Async job ingestion pipeline with LLM screening.",
            "framings": {"devops": {"bullets": ["Built an async ingestion pipeline."]}},
            "skills": {"core": ["python", "llm", "data_pipeline", "sql"],
                       "supporting": ["llm_eval", "rest_api", "observability"]},
        }],
        "portfolio_catalog": catalog,
    }
    path = tmp_path_factory.mktemp("profile") / "profile.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def pool(profile_path):
    return load_portfolio(profile_path)


@pytest.fixture(scope="module")
def scorer(pool):
    # Fixed rarity so tests don't depend on data/skill_idf.json.
    return ProjectScorer(pool, idf={"python": 0.5, "aws": 0.7, "kubernetes": 1.0})


SYSADMIN_JD = """
About the role
You will run our Windows and Linux server estate.

Requirements:
- Active Directory, Group Policy and Entra ID administration
- PowerShell scripting to automate user onboarding
- Veeam backup and disaster recovery testing
- VMware vSphere and storage (NetApp, NFS)

Benefits:
- Kubernetes-themed hackathons and free AWS credits
"""

SIEM_JD = """
Responsibilities:
- Triage SIEM alerts in Splunk and lead incident response
- Tune threat detection rules and harden endpoints (CIS benchmarks)
- Drive zero trust rollout
"""

MLOPS_JD = """
What you'll do:
- Serve LLMs with vLLM on GPU nodes in Kubernetes
- Own the MLflow model registry and model deployment pipeline
- PyTorch experience required
"""


class TestPortfolio:
    def test_pool_has_profile_and_catalog_projects(self, pool):
        kinds = {p.kind for p in pool}
        assert kinds == {"profile", "catalog"}
        assert len([p for p in pool if p.kind == "catalog"]) == 15

    def test_every_tag_is_a_taxonomy_key(self, pool):
        for p in pool:
            assert set(p.tags) <= set(SKILLS), p.id

    def test_catalog_prompt_block_carries_target_metrics_and_bullets(self, pool):
        hybridid = next(p for p in pool if p.id == "hybridid")
        assert "Target metrics" in hybridid.prompt_block
        assert "Reference bullets" in hybridid.prompt_block
        assert "Likely interview questions" not in hybridid.prompt_block

    def test_strip_top_level_keys_keeps_other_blocks_verbatim(self):
        raw = "a: 1\n# note\nprojects:\n  - name: x\n    y: 2\nskills:\n  cloud: [aws]\n"
        out = strip_top_level_keys(raw, ("projects",))
        assert out == "a: 1\n# note\nskills:\n  cloud: [aws]\n"

    def test_unknown_skill_tag_is_rejected(self, tmp_path):
        profile = tmp_path / "profile.yaml"
        profile.write_text(
            'projects:\n  - name: "X"\n    skills:\n      core: [not_a_skill]\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="unknown skill tag"):
            load_portfolio(profile)

    def test_catalog_summary_lists_only_catalog_projects(self, pool):
        summary = catalog_summary(pool)
        assert "HybridID" in summary
        assert "DiaSense AI" not in summary
        assert len(summary.splitlines()) == 15


class TestJdWeights:
    def test_boilerplate_sections_get_no_weight(self, scorer):
        w = scorer.jd_weights("Systems Administrator", SYSADMIN_JD)
        assert "active_directory" in w
        assert "kubernetes" not in w   # only mentioned under Benefits

    def test_preferred_section_is_half_weight(self, scorer):
        jd = "Requirements:\n- Terraform\n\nNice to have:\n- Ansible\n"
        w = scorer.jd_weights("Engineer", jd)
        assert w["ansible"] == pytest.approx(w["terraform"] * 0.5)

    def test_inline_preferred_is_half_weight(self):
        lines = dict(_line_weights("Requirements:\n- Go experience a plus\n- Python\n"))
        assert lines["- Go experience a plus"] == 0.5
        assert lines["- Python"] == 1.0

    def test_title_skill_is_boosted(self, scorer):
        jd = "Requirements:\n- Terraform\n"
        w = scorer.jd_weights("Azure Engineer", jd)
        assert w["azure"] == pytest.approx(w["terraform"] * 2)

    def test_rare_skills_outweigh_common_ones(self, scorer):
        jd = "Requirements:\n- Python\n- Kubernetes\n"
        w = scorer.jd_weights("Engineer", jd)
        assert w["kubernetes"] > w["python"]


class TestSelection:
    def test_sysadmin_jd_picks_identity_and_backup_projects(self, scorer):
        sel = scorer.select("Windows Systems Administrator", SYSADMIN_JD)
        assert set(sel.ids[:2]) == {"hybridid", "restorepoint"}

    def test_siem_jd_picks_bluewatch_first(self, scorer):
        sel = scorer.select("Security Operations Engineer", SIEM_JD)
        assert sel.ids[0] == "bluewatch"

    def test_mlops_jd_picks_inference_platform(self, scorer):
        sel = scorer.select("MLOps Engineer", MLOPS_JD)
        assert sel.ids[0] == "inferencestack"

    def test_sparse_ai_jd_is_decided_by_the_title_not_boilerplate(self, scorer):
        jd = ("Key Responsibilities:\n- Build applications that use LLMs, voice and chat\n"
              "- Ship with a focus on security, reliability and HIPAA compliance\n")
        sel = scorer.select("AI Engineer", jd)
        assert {"runbookrag", "opsagent"} & set(sel.ids[:2])
        assert not {"hybridid", "fleetforge"} & set(sel.ids)

    def test_always_three_distinct_projects(self, scorer):
        sel = scorer.select("Platform Engineer", "Requirements:\n- Kubernetes, Helm, Argo CD\n")
        assert len(sel.ids) == 3 == len(set(sel.ids))

    def test_second_pick_covers_what_first_missed(self, pool):
        a = PortfolioProject("a", "A", "catalog", {"kubernetes": 1.0, "helm": 1.0})
        b = PortfolioProject("b", "B", "catalog", {"kubernetes": 1.0, "helm": 0.5})
        c = PortfolioProject("c", "C", "catalog", {"active_directory": 1.0})
        s = ProjectScorer([a, b, c], idf={})
        jd = "Requirements:\n- Kubernetes and Helm\n- Active Directory\n"
        assert s.select("Engineer", jd, k=2).ids == ["a", "c"]

    def test_empty_description_falls_back_to_profile_projects(self, scorer):
        sel = scorer.select("Engineer", "")
        assert sel.picks[0].project.kind == "profile"

    def test_coverage_and_uncovered_are_reported(self, scorer):
        sel = scorer.select("Windows Systems Administrator", SYSADMIN_JD)
        assert 0 < sel.coverage <= 1
        d = sel.as_dict()
        assert [p["id"] for p in d["projects"]] == sel.ids

    def test_prompt_block_lists_emphasis_per_project(self, scorer):
        block = scorer.select("Windows Systems Administrator", SYSADMIN_JD).prompt_block()
        assert block.count("Emphasize for this JD:") == 3
        assert "### HybridID" in block


class TestTaxonomy:
    @pytest.mark.parametrize("text,absent", [
        ("Offices in San Francisco and San Jose", "storage"),
        ("We are SOC 2 Type II certified", "security_ops"),
        ("Call our REST endpoint", "endpoint_mgmt"),
        ("Ready to go to market with us", "go"),
        ("Support the Microsoft Red Team's attack infrastructure", "llm_eval"),
    ])
    def test_ambiguous_words_do_not_match(self, text, absent):
        assert absent not in extract(text)

    @pytest.mark.parametrize("text,present", [
        ("Experience with Go, Python", "go"),
        ("Golang services", "go"),
        ("Manage SAN and NAS arrays", "storage"),
        ("Staff our SOC", "security_ops"),
    ])
    def test_real_mentions_match(self, text, present):
        assert present in extract(text)


class TestResumeEngineProjects:
    def test_system_prompt_excludes_projects_and_dynamic_prompt_has_selection(self, profile_path):
        from generation.resume_engine import ResumeEngine
        engine = ResumeEngine(profile_path=str(profile_path))
        sys_prompt = engine._build_system_prompt()
        assert "portfolio_catalog:" not in sys_prompt
        assert "\nprojects:" not in sys_prompt

        with patch("generation.resume_engine.run_claude", return_value=None) as mock_run:
            engine.generate(company="Acme", title="Windows Systems Administrator",
                            location="Remote", description=SYSADMIN_JD, source="linkedin")
        dynamic = mock_run.call_args.args[0]
        assert "{{selected_projects}}" not in dynamic
        assert "### HybridID" in dynamic
        assert "Emphasize for this JD:" in dynamic
