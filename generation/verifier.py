"""Resume + cover letter verification via a Claude "senior technical recruiter"
pass.

Scores interview likelihood (0-100), lists concrete gaps + actionable fixes,
and flags recruiter-screen tells (over-claiming, AI-slop, visa mentions, etc.).
generate_materials uses this to iterate: a draft scoring below the configured
threshold is regenerated with the fixes fed back in. A free, deterministic
keyword-coverage signal is computed locally and passed into the prompt so the
recruiter sim has objective ATS data to anchor on. See config.RESUME_VERIFICATION_*.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from config import RESUME_GENERATION_MODEL, RESUME_VERIFIER_TIMEOUT
from generation.claude_cli import run_claude, extract_json

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "resume_verification.md"


def _resume_text(resume_data: dict) -> str:
    """Flatten the generated resume into one lowercase string for keyword
    coverage. Strips ** bold markers so they don't break substring matching."""
    resume = resume_data.get("resume", {}) or {}
    parts: list[str] = [resume.get("summary", "") or ""]
    for exp in resume.get("experience", []) or []:
        parts.extend(exp.get("bullets", []) or [])
    for proj in resume.get("projects", []) or []:
        parts.extend(proj.get("bullets", []) or [])
    for items in (resume.get("skills", {}) or {}).values():
        parts.extend(str(i) for i in items)
    return " ".join(parts).replace("*", "").lower()


def keyword_coverage(resume_data: dict, jd_keywords: list[str]) -> tuple[float, list[str]]:
    """Return (coverage_fraction, missing_keywords) for the JD's top keywords."""
    kws = [k.strip() for k in (jd_keywords or []) if k and k.strip()]
    if not kws:
        return 1.0, []
    text = _resume_text(resume_data)
    missing = [k for k in kws if k.lower() not in text]
    return (len(kws) - len(missing)) / len(kws), missing


def format_feedback(vr: dict) -> str:
    """Turn a verification result into a punch list for the next generation pass."""
    lines: list[str] = []
    score = vr.get("interview_likelihood")
    if score is not None:
        lines.append(f"Previous draft scored {score}/100 on interview likelihood.")
    for label, key in (
        ("Gaps to close", "gaps"),
        ("Required fixes (apply each)", "fixes"),
        ("Red flags to remove", "red_flags"),
    ):
        items = vr.get(key) or []
        if items:
            lines.append(f"{label}:")
            lines.extend(f"  - {it}" for it in items)
    return "\n".join(lines)


class ResumeVerifier:
    def verify(
        self, *, resume_data: dict, cover_letter: str,
        company: str, title: str, location: str, description: str,
        jd_keywords: list[str],
    ) -> dict | None:
        """Score the materials. Returns the parsed verdict dict or None on failure
        (callers treat None as "could not verify — keep the draft")."""
        coverage, missing = keyword_coverage(resume_data, jd_keywords)
        if jd_keywords:
            present = len(jd_keywords) - len(missing)
            coverage_str = f"{coverage * 100:.0f}% ({present}/{len(jd_keywords)} present"
            coverage_str += f"; missing: {', '.join(missing)})" if missing else ")"
        else:
            coverage_str = "n/a (no JD keywords extracted)"

        template = PROMPT_PATH.read_text(encoding="utf-8")
        prompt = (
            template
            .replace("{{company}}", company)
            .replace("{{title}}", title)
            .replace("{{location}}", location)
            .replace("{{description}}", description or "")
            .replace("{{jd_keywords}}", ", ".join(jd_keywords) if jd_keywords else "(none extracted)")
            .replace("{{keyword_coverage}}", coverage_str)
            .replace("{{resume_json}}", json.dumps(resume_data.get("resume", {}), indent=2))
            .replace("{{cover_letter}}", cover_letter or "(none)")
        )
        output = run_claude(
            prompt, model=RESUME_GENERATION_MODEL,
            timeout=RESUME_VERIFIER_TIMEOUT, label="Recruiter-sim verify",
            purpose="verification",
        )
        return self._parse_response(output) if output else None

    def _parse_response(self, text: str) -> dict | None:
        data = extract_json(text)
        if data is None:
            logger.warning(f"Verifier: failed to parse JSON: {(text or '')[:200]}")
            return None
        if not isinstance(data, dict) or "interview_likelihood" not in data:
            logger.warning(f"Verifier: response missing interview_likelihood: {str(data)[:200]}")
            return None
        return data
