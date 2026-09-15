"""Regression tests for ATS-safe resume rendering.

These lock in fixes for two defects measured across 619 generated resumes:
orphaned <li> marker glyphs corrupting PDF reading order, and skill strings
Workday's taxonomy matcher cannot match.
"""
from __future__ import annotations

import re

import pytest

from generation.ats import normalize_skill_items, sanitize_text


# ── Character sanitization ───────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("<1s answer latency", "under 1s answer latency"),
    (">50% faster", "over 50% faster"),
    ("handled 100+ calls — solving the problem", "handled 100+ calls - solving the problem"),
    ("June 2024 – Present", "June 2024 - Present"),
    ("email thread → ticket", "email thread to ticket"),
    ("PostgreSQL · Redis · SQLite", "PostgreSQL, Redis, SQLite"),
    ("Python↔hardware bridge", "Python to hardware bridge"),
    ("Observability & Monitoring", "Observability and Monitoring"),
    ("the company’s infrastructure", "the company's infrastructure"),
    ("“quoted” text", '"quoted" text'),
])
def test_sanitize_text(raw, expected):
    assert sanitize_text(raw) == expected


def test_sanitize_output_is_pure_ascii():
    messy = "Deployed ✓ ≥ 5 services — at <2s × latency… ™"
    assert sanitize_text(messy).isascii()


def test_ampersand_preserved_in_locked_identity_strings():
    """Locked titles are cross-checked against LinkedIn character-for-character."""
    title = "AI & Cloud Infrastructure Engineer"
    assert sanitize_text(title, preserve_ampersand=True) == title
    assert sanitize_text(title) == "AI and Cloud Infrastructure Engineer"


def test_ampersand_inside_a_token_is_never_split():
    """MITRE ATT&CK and R&D are single tokens, not 'X and Y'."""
    assert sanitize_text("MITRE ATT&CK") == "MITRE ATT&CK"
    assert sanitize_text("R&D tooling") == "R&D tooling"


# ── Skill normalization ──────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    # Cloud platforms: children read naturally as "<platform> <service>".
    (["AWS (EC2, S3, Lambda)"], ["AWS", "AWS EC2", "AWS S3", "AWS Lambda"]),
    (["Azure (App Service)"], ["Azure", "Azure App Service"]),
    # Non-platform parents emit the child standalone -- "Spring Boot", not
    # "Java Spring Boot", which is not a skill anyone searches for.
    (["Java (Spring Boot)"], ["Java", "Spring Boot"]),
    # Prose parentheticals are proficiency notes, not skills.
    (["Ansible (RH294 certified)"], ["Ansible"]),
    (["Cloudflare Workers (edge serverless)"], ["Cloudflare Workers"]),
    (["Claude Code (agents, skills, context management)"], ["Claude Code"]),
    (["GCP (Compute Engine, certified ACE)"], ["GCP", "GCP Compute Engine"]),
    # Slash-joined pairs are two separate skills...
    (["JavaScript/TypeScript"], ["JavaScript", "TypeScript"]),
    (["TLS/SSL"], ["TLS", "SSL"]),
    # ...unless the slash is part of the name.
    (["TCP/IP"], ["TCP/IP"]),
    (["CI/CD"], ["CI/CD"]),
    # Deduplication is case-insensitive.
    (["Docker", "docker", "Kubernetes"], ["Docker", "Kubernetes"]),
])
def test_normalize_skill_items(raw, expected):
    assert normalize_skill_items(raw) == expected


def test_no_unbalanced_parens_survive():
    """The core Workday failure: comma-splitting `AWS (EC2, S3)` yields
    `AWS (EC2` and `S3)`, neither of which matches any taxonomy entry."""
    items = normalize_skill_items([
        "AWS (EC2, S3, Lambda, EKS, CloudFormation, VPC, GuardDuty, WAF, Cognito)",
        "Kubernetes (EKS, cluster automation)",
    ])
    for item in items:
        assert item.count("(") == item.count(")"), item
    assert not any("," in item for item in items)


def test_bold_marker_survives_on_first_derived_token():
    out = normalize_skill_items(["**Kubernetes (EKS)**", "Docker"])
    assert out[0] == "**Kubernetes**"
    assert "**" not in out[1]


def test_category_is_capped():
    many = [f"Skill{i}" for i in range(40)]
    assert len(normalize_skill_items(many)) <= 12


# ── End-to-end PDF text layer ────────────────────────────────────────────────

RESUME_FIXTURE = {
    "resume": {
        "personal": {"location": "Austin, TX"},
        "summary": "Engineer shipping services with <1s latency — at scale.",
        "experience": [{
            "title": "AI & Cloud Infrastructure Engineer",
            "company": "KV Bits", "location": "Chicago, IL",
            "period": "June 2024 – Present",
            "bullets": [f"Bullet {i} describing a **quantified** outcome." for i in range(5)],
        }],
        "education": [{
            "school": "Illinois Institute of Technology, Chicago, IL",
            "degree": "MS, Computer and Information Systems", "gpa": "4.0",
            "graduation": "May 2025",
        }],
        "skills": {
            "Observability & Monitoring": ["Prometheus", "Grafana"],
            "Cloud": ["AWS (EC2, S3, Cognito)", "JavaScript/TypeScript", "TCP/IP"],
        },
        "certifications": [{"name": "CompTIA Security+", "issuer": "CompTIA", "issued": "02/23/2025"}],
        "projects": [{
            "name": "AI Email Triage & JIRA Auto-Ticketing Workflow",
            "bullets": [f"Project bullet {i}." for i in range(4)],
        }],
    }
}


def _resume_text_layer(tmp_path) -> str:
    fitz = pytest.importorskip("fitz", reason="PyMuPDF needed to read the text layer")
    from generation.pdf_renderer import render_resume_pdf

    out = tmp_path / "resume.pdf"
    if not render_resume_pdf(RESUME_FIXTURE, out):
        pytest.skip("WeasyPrint native libraries unavailable")
    doc = fitz.open(out)
    try:
        return "".join(page.get_text() for page in doc)
    finally:
        doc.close()


def test_no_orphaned_bullet_markers(tmp_path):
    """The defect that split the Skills section in 602/619 surveyed resumes."""
    text = _resume_text_layer(tmp_path)
    orphans = [ln for ln in text.split("\n") if ln.strip() in ("•", "-")]
    assert not orphans, f"{len(orphans)} orphaned marker lines in the text layer"


def test_every_bullet_glyph_is_attached_to_its_text(tmp_path):
    text = _resume_text_layer(tmp_path)
    for line in text.split("\n"):
        if "•" in line:
            assert len(line.strip()) > 2, f"bare marker line: {line!r}"


def test_skills_block_has_no_unmatchable_tokens(tmp_path):
    text = _resume_text_layer(tmp_path)
    block = re.search(r"\nSKILLS\n(.*?)\n(CERTIFICATIONS|PROJECTS)\n", text, re.S)
    assert block, "SKILLS section not found in text layer"
    body = block.group(1)
    assert "(" not in body and ")" not in body
    assert "AWS EC2" in body and "AWS S3" in body


def test_text_layer_carries_no_stray_markup_chars(tmp_path):
    text = _resume_text_layer(tmp_path)
    assert "<" not in text and ">" not in text
    assert "under 1s latency" in text


def test_locked_title_keeps_its_ampersand(tmp_path):
    text = _resume_text_layer(tmp_path)
    assert "AI & Cloud Infrastructure Engineer" in text
    assert "AI Email Triage & JIRA Auto-Ticketing Workflow" in text
    # ...while a non-identity label is converted.
    assert "Observability and Monitoring" in text
