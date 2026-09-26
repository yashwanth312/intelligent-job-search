"""Deterministic per-JD project selection — no Claude call, milliseconds per job.

Picks the resume's 3 project slots from the portfolio pool
(generation.portfolio) so only those 3 projects reach the generation prompt.

1. JD skill weights. Every canonical skill found in the title/description gets
       rarity x section x repetition x title_boost
   - rarity: log(N / (1 + df)) from data/skill_idf.json, so "python" (~60% of
     postings) counts far less than "active directory" (~8%). Without this the
     same AWS/Kubernetes projects win every JD.
   - section: required/responsibilities text 1.0, preferred / nice-to-have
     0.5, boilerplate (about us, benefits, EEO, pay) 0. Text before any header
     is 0.8. A skill takes the best section it appears in.
   - repetition: 1 + 0.5 * ln(mentions), mentions capped at 4.
   - title_boost: x2 when the skill is in the job title, or implied by a title
     word such as "AI", "SRE" or "Network" (see _TITLE_HINTS).
2. Project score = sum(jd_weight x tag_depth) over shared skills, divided by
   the L2 norm of the project's tag depths so long tag lists don't win by bulk.
   Tag depths: core 1.0, supporting 0.5, touch 0.2.
3. Diversity. Picks are greedy: after each pick, a skill it already covers
   counts at (1 - 0.7 x covered_depth) for the next pick, so pick 2 wins by
   covering what pick 1 missed rather than repeating it.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from generation.portfolio import PortfolioProject
from generation.skill_taxonomy import count, extract, label

ROOT = Path(__file__).resolve().parent.parent
IDF_PATH = ROOT / "data" / "skill_idf.json"

TITLE_BOOST = 2.0
REPEAT_DISCOUNT = 0.7
MENTION_CAP = 4
IDF_FLOOR = 0.1
DEFAULT_SECTION_WEIGHT = 0.8
PREFERRED_WEIGHT = 0.5

_ROLE_HEAD = re.compile(r"about (the|this) (role|job|position|opportunity)")
_ZERO_HEAD = re.compile(
    r"^(about\b|benefits|perks|what we offer|equal (employment )?opportunity|eeo\b"
    r"|compensation|pay (range|transparency)|salary|base pay|why (join|work)"
    r"|our (values|culture|mission|story)|life at|who we are|additional information"
    r"|disclaimer|accommodation|total rewards)"
)
_PREF_HEAD = re.compile(r"preferred|nice[- ]to[- ]have|bonus|desired|pluses|good to have|a plus|extra credit")
_REQ_HEAD = re.compile(
    r"requirement|qualification|must[- ]have|what you('| wi)ll (need|do|bring)"
    r"|what we('re| are) looking for|you (have|bring|will)|responsibilit|skills"
    r"|experience|your impact|the role|day[- ]to[- ]day"
)
# Title words that name a skill family even when the description never lists
# its tools. Bare "AI" is too common in descriptions to be a skill alias, but
# in a title ("AI Engineer") it is the strongest signal there is; without this
# a sparse AI JD was decided by a generic requirement like HIPAA compliance.
_TITLE_HINTS: list[tuple[re.Pattern[str], tuple[str, ...]]] = [
    (re.compile(r"\b(ai|genai|gen ai|generative|llm|agentic)\b"), ("llm", "agents", "rag", "llm_eval")),
    (re.compile(r"\b(ml|machine learning|mlops)\b"), ("mlops", "ml_frameworks")),
    (re.compile(r"\b(sre|reliability)\b"), ("slo", "incident_response", "observability")),
    (re.compile(r"\b(devops|platform)\b"), ("cicd",)),
    (re.compile(r"\bnetwork"), ("networking", "routing_switching")),
    (re.compile(r"\b(systems? administrator|sysadmin)\b"), ("linux", "windows_server")),
    (re.compile(r"\bwindows\b"), ("windows_server",)),
    (re.compile(r"\bidentity\b"), ("sso_identity", "active_directory")),
]
_PREF_INLINE = re.compile(r"preferred|nice[- ]to[- ]have|\ba plus\b|\bbonus\b|desirable")
_MD = re.compile(r"[*#_`>\\]+")
_BULLET = re.compile(r"^(?:[-•·–◦▪]|\d+[.)])\s*")


def _is_header(clean: str) -> bool:
    return (0 < len(clean) <= 60 and len(clean.split()) <= 7
            and not clean.endswith(".") and not _BULLET.match(clean))


def _line_weights(description: str) -> list[tuple[str, float]]:
    """(line, section weight) for every non-empty description line."""
    weight = DEFAULT_SECTION_WEIGHT
    out: list[tuple[str, float]] = []
    for raw in (description or "").splitlines():
        clean = _MD.sub("", raw).strip().lower().rstrip(":").strip()
        if not clean:
            continue
        # A header switches the section weight; its own text still counts as
        # content ("Kubernetes experience" can be either).
        if _is_header(clean):
            if _ROLE_HEAD.search(clean):
                weight = 1.0
            elif _ZERO_HEAD.search(clean):
                weight = 0.0
            elif _PREF_HEAD.search(clean):
                weight = PREFERRED_WEIGHT
            elif _REQ_HEAD.search(clean):
                weight = 1.0
        line_w = min(weight, PREFERRED_WEIGHT) if _PREF_INLINE.search(clean) else weight
        out.append((raw, line_w))
    return out


def load_idf(path: Path = IDF_PATH) -> dict[str, float]:
    """Skill -> inverse document frequency. Missing file => every skill 1.0."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    n = data["n_docs"]
    return {k: max(IDF_FLOOR, math.log(n / (1 + df))) for k, df in data["df"].items()}


@dataclass
class Pick:
    project: PortfolioProject
    score: float
    matched: list[str]            # shared skills, most JD-weighted first


@dataclass
class Selection:
    picks: list[Pick]
    coverage: float               # share of JD skill weight the picks cover
    uncovered: list[str]          # heaviest JD skills no pick covers
    jd_weights: dict[str, float] = field(default_factory=dict)

    @property
    def ids(self) -> list[str]:
        return [p.project.id for p in self.picks]

    @property
    def names(self) -> list[str]:
        return [p.project.name for p in self.picks]

    def prompt_block(self) -> str:
        parts = []
        for i, pick in enumerate(self.picks, 1):
            emphasis = ", ".join(label(s) for s in pick.matched) or "general relevance"
            parts.append(f"{pick.project.prompt_block}\nRank {i}. Emphasize for this JD: {emphasis}")
        return "\n\n".join(parts)

    def as_dict(self) -> dict:
        return {
            "projects": [
                {"id": p.project.id, "name": p.project.name, "kind": p.project.kind,
                 "score": round(p.score, 3), "matched": p.matched}
                for p in self.picks
            ],
            "coverage": round(self.coverage, 3),
            "uncovered": self.uncovered,
        }


class ProjectScorer:
    def __init__(self, pool: list[PortfolioProject], idf: dict[str, float] | None = None):
        self.pool = pool
        self.idf = load_idf() if idf is None else idf
        self._norms = {p.id: math.sqrt(sum(d * d for d in p.tags.values())) for p in pool}

    def jd_weights(self, title: str, description: str) -> dict[str, float]:
        section: dict[str, float] = {}
        for line, w in _line_weights(description):
            for skill in extract(line):
                section[skill] = max(section.get(skill, 0.0), w)
        in_title = extract(title)
        title_lower = title.lower()
        for rx, hinted in _TITLE_HINTS:
            if rx.search(title_lower):
                in_title.update(hinted)
        for skill in in_title:
            section[skill] = 1.0
        mentions: Counter[str] = count(f"{title}\n{description}")

        weights: dict[str, float] = {}
        for skill, sec in section.items():
            if sec <= 0:
                continue
            reps = 1 + 0.5 * math.log(min(max(mentions[skill], 1), MENTION_CAP))
            boost = TITLE_BOOST if skill in in_title else 1.0
            weights[skill] = self.idf.get(skill, 1.0) * sec * reps * boost
        return weights

    def _score(self, p: PortfolioProject, w: dict[str, float], covered: dict[str, float]) -> float:
        raw = sum(w[s] * d * (1 - REPEAT_DISCOUNT * covered.get(s, 0.0))
                  for s, d in p.tags.items() if s in w)
        return raw / self._norms[p.id]

    def select(self, title: str, description: str, k: int = 3) -> Selection:
        w = self.jd_weights(title, description)
        covered: dict[str, float] = {}
        picks: list[Pick] = []
        order = {p.id: i for i, p in enumerate(self.pool)}

        for _ in range(min(k, len(self.pool))):
            remaining = [p for p in self.pool if p.id not in {x.project.id for x in picks}]
            # Ties (including an empty JD) fall back to profile projects, then pool order.
            best = max(remaining, key=lambda p: (
                self._score(p, w, covered), p.kind == "profile", -order[p.id]))
            matched = sorted((s for s in best.tags if s in w),
                             key=lambda s: w[s] * best.tags[s], reverse=True)[:6]
            picks.append(Pick(best, self._score(best, w, covered), matched))
            for s, d in best.tags.items():
                covered[s] = max(covered.get(s, 0.0), d)

        total = sum(w.values())
        coverage = (sum(v * min(1.0, covered.get(s, 0.0)) for s, v in w.items()) / total) if total else 0.0
        uncovered = sorted((s for s in w if s not in covered), key=w.get, reverse=True)[:8]
        return Selection(picks, coverage, uncovered, w)
