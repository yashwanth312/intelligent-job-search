"""Portfolio project pool — profile.yaml projects plus the docs/projects catalog.

Two kinds of project feed the resume's three project slots:
  * profile projects (`projects:` in profile.yaml) — built work with raw_context
  * catalog projects (`portfolio_catalog:` pointers to docs/projects/*.md) —
    specs the candidate is building; the spec's target metrics are the only
    numbers a resume may claim for them

Both are tagged with generation.skill_taxonomy keys (profile: `skills:` block;
catalog: spec front matter) so generation.project_scorer can rank them per JD.
Build status is deliberately NOT modelled here: the generator may select any
project (user decision 2026-09-26); status lives in the project tracker.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from generation.skill_taxonomy import SKILLS, label
from models.profile import CatalogRef, Project

ROOT = Path(__file__).resolve().parent.parent

DEPTH_WEIGHTS = {"core": 1.0, "supporting": 0.5, "touch": 0.2}

# profile.yaml keys that are rendered per job (selected projects only) rather
# than shipped whole in the cached system prompt.
PER_JOB_PROFILE_KEYS = ("projects", "portfolio_catalog")

_TOP_LEVEL_KEY = re.compile(r"^[A-Za-z_][\w-]*\s*:")
_FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
_H2 = re.compile(r"^## +(.+?)\s*$", re.M)


@dataclass(frozen=True)
class PortfolioProject:
    id: str
    name: str
    kind: str                      # "profile" | "catalog"
    tags: dict[str, float]         # skill key -> depth weight
    tagline: str = ""
    prompt_block: str = ""         # material the generation prompt gets
    core: tuple[str, ...] = field(default_factory=tuple)


def _tags(skills: dict, where: str) -> dict[str, float]:
    tags: dict[str, float] = {}
    for depth in ("touch", "supporting", "core"):   # deepest wins on duplicates
        for key in skills.get(depth, []) or []:
            if key not in SKILLS:
                raise ValueError(f"{where}: unknown skill tag '{key}'")
            tags[key] = DEPTH_WEIGHTS[depth]
    if not tags:
        raise ValueError(f"{where}: no skill tags")
    return tags


def parse_spec(path: Path) -> tuple[dict, dict[str, str]]:
    """Return (front_matter, {h2 heading: body}) for a project spec."""
    text = path.read_text(encoding="utf-8")
    m = _FRONT_MATTER.match(text)
    if not m:
        raise ValueError(f"{path}: missing YAML front matter")
    meta = yaml.safe_load(m.group(1)) or {}
    body = text[m.end():]
    sections: dict[str, str] = {}
    heads = list(_H2.finditer(body))
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        sections[h.group(1)] = body[h.end():end].strip()
    return meta, sections


def _section(sections: dict[str, str], prefix: str) -> str:
    for head, text in sections.items():
        if head.lower().startswith(prefix.lower()):
            return text
    return ""


def _catalog_block(name: str, tagline: str, sections: dict[str, str]) -> str:
    # Approach/architecture stay out: the reference bullets already carry the
    # substance, and this block is uncached per-job prompt text.
    return "\n".join([
        f"### {name}",
        f"Portfolio project — {tagline}",
        "Problem:", _section(sections, "Problem"),
        "Target metrics (the ONLY numbers you may use for this project):",
        _section(sections, "Target metrics"),
        "Reference bullets (rewrite for this JD; add no numbers beyond the target metrics):",
        _section(sections, "Draft resume bullets"),
    ])


def _profile_block(project) -> str:
    bullets = [b for fr in project.framings.values() for b in (fr or {}).get("bullets", [])]
    lines = [f"### {project.name}", "Built project. Every claim must trace to this context:",
             project.raw_context.strip()]
    if bullets:
        lines.append("Reference bullets:")
        lines.extend(f"- {b}" for b in bullets)
    return "\n".join(lines)


def load_portfolio(profile_path: str | Path = "profile.yaml") -> list[PortfolioProject]:
    path = Path(profile_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    projects = [Project(**p) for p in data.get("projects") or []]
    catalog = [CatalogRef(**c) for c in data.get("portfolio_catalog") or []]
    pool: list[PortfolioProject] = []

    for p in projects:
        pid = p.id or re.sub(r"[^a-z0-9]+", "-", p.name.lower()).strip("-")
        pool.append(PortfolioProject(
            id=pid, name=p.name, kind="profile",
            tags=_tags(p.skills.model_dump(), f"profile project '{p.name}'"),
            prompt_block=_profile_block(p), core=tuple(p.skills.core),
        ))

    for ref in catalog:
        spec = (path.parent / ref.spec) if not Path(ref.spec).is_absolute() else Path(ref.spec)
        meta, sections = parse_spec(spec)
        if meta.get("id") != ref.id:
            raise ValueError(f"{spec}: front-matter id '{meta.get('id')}' != profile id '{ref.id}'")
        skills = meta.get("skills") or {}
        tagline = meta.get("tagline", "")
        pool.append(PortfolioProject(
            id=ref.id, name=ref.name, kind="catalog",
            tags=_tags(skills, str(spec)), tagline=tagline,
            prompt_block=_catalog_block(ref.name, tagline, sections),
            core=tuple(skills.get("core", []) or []),
        ))

    ids = [p.id for p in pool]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate project ids in portfolio: {ids}")
    return pool


def strip_top_level_keys(raw_yaml: str, keys: tuple[str, ...]) -> str:
    """Drop whole top-level blocks (`key:` through the next top-level key)
    from YAML text without re-serializing, so comments and formatting of the
    rest survive byte-for-byte (the cached system prompt must stay stable)."""
    out: list[str] = []
    skipping = False
    for line in raw_yaml.splitlines(keepends=True):
        if _TOP_LEVEL_KEY.match(line):
            skipping = line.split(":", 1)[0].strip() in keys
        if not skipping:
            out.append(line)
    return "".join(out)


def catalog_summary(pool: list[PortfolioProject]) -> str:
    """One line per catalog project for the Stage 2 screening prompt."""
    return "\n".join(
        f"- {p.name}: {p.tagline} (core: {', '.join(label(s) for s in p.core)})"
        for p in pool if p.kind == "catalog"
    )
