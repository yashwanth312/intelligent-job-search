"""Resume + cover letter generation via Claude Code CLI.

A SINGLE Claude CLI call returns both the structured resume JSON and the
cover letter text. ANTHROPIC_API_KEY is purged from the subprocess env so the
call always uses the user's Max subscription via the Claude CLI session,
never pay-per-token API credits.

The prompt template is split at its ``## Job Description`` / ``## LOCKED
CONSTANTS`` headers: everything outside that span (the intro + the full
profile.yaml vault) is constant across every job in a run and is sent via
``--system-prompt-file`` so it's cached server-side instead of re-billed as
cache-creation on every call; only the per-job dynamic slice (company, title,
location, source, screening notes, description, revision feedback) is piped
on stdin. Neither channel hits Windows' ~32KB argv limit since nothing goes
through argv. Extended thinking is disabled for this call (see
generation.claude_cli.run_claude) — it's ~86% of a generation call's billed
output and is discarded, never surfaced to callers.

Projects are the one per-job part of the profile. The profile's `projects` and
`portfolio_catalog` blocks are stripped from the cached system prompt;
generation.project_scorer picks 3 projects for each JD (no Claude call) and
only those 3 are rendered into the dynamic slice as {{selected_projects}}.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from config import RESUME_GENERATION_MODEL, RESUME_GENERATION_TIMEOUT
from generation.claude_cli import run_claude, extract_json
from generation.portfolio import PER_JOB_PROFILE_KEYS, load_portfolio, strip_top_level_keys
from generation.project_scorer import ProjectScorer, Selection

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "application_materials.md"

_JOB_SECTION_START = "## Job Description"
_JOB_SECTION_END = "## LOCKED CONSTANTS"


class ResumeEngine:
    def __init__(self, profile_path: str = "profile.yaml"):
        with open(profile_path, encoding="utf-8") as f:
            self._profile_raw = f.read()
        self._profile = yaml.safe_load(self._profile_raw)
        self._profile_prompt = strip_top_level_keys(self._profile_raw, PER_JOB_PROFILE_KEYS)
        self._scorer = ProjectScorer(load_portfolio(profile_path))
        self._system_prompt: str | None = None

    def _build_system_prompt(self) -> str:
        """Static instructions + profile, minus the per-job dynamic slice.

        Memoized — the profile and instructions don't change across jobs in a
        run, so this is built once and reused byte-identical on every call
        (required for the server-side prompt cache to actually hit).
        """
        if self._system_prompt is not None:
            return self._system_prompt
        template = PROMPT_PATH.read_text(encoding="utf-8")
        before, rest = template.split(_JOB_SECTION_START, 1)
        _job_section, after = rest.split(_JOB_SECTION_END, 1)
        self._system_prompt = (
            before.replace("{{profile_yaml}}", self._profile_prompt)
            + _JOB_SECTION_END + after
        )
        return self._system_prompt

    def generate(
        self, company: str, title: str, location: str,
        description: str, source: str, screening_notes: str = "",
        revision_feedback: str = "",
    ) -> dict | None:
        """Generate resume + cover letter for one job in a single Claude call.

        `revision_feedback` carries a recruiter-review punch list from a prior
        draft (see generation.verifier). When provided, the model revises the
        previous draft to address each fix; when empty it generates fresh.

        Returns a dict shaped like:
          {"resume": {...}, "decisions": {...}, "cover_letter": "...",
           "_project_selection": {...}}
        or None if the call or parse failed. The selection is deterministic
        for a given title + description, so a revision pass gets the same 3.
        """
        selection = self.select_projects(title, description)
        template = PROMPT_PATH.read_text(encoding="utf-8")
        _before, rest = template.split(_JOB_SECTION_START, 1)
        job_section, _after = rest.split(_JOB_SECTION_END, 1)
        dynamic_prompt = (
            _JOB_SECTION_START + job_section
        ).replace(
            "{{company}}", company
        ).replace(
            "{{title}}", title
        ).replace(
            "{{location}}", location
        ).replace(
            "{{source}}", source
        ).replace(
            "{{screening_notes}}", screening_notes
        ).replace(
            "{{description}}", description or ""
        ).replace(
            "{{selected_projects}}", selection.prompt_block() or "None"
        ).replace(
            "{{revision_feedback}}", revision_feedback.strip() or "None"
        )
        output = run_claude(
            dynamic_prompt, model=RESUME_GENERATION_MODEL,
            timeout=RESUME_GENERATION_TIMEOUT, label="Materials generation",
            purpose="generation",
            system_prompt=self._build_system_prompt(),
            disable_thinking=True,
        )
        result = self._parse_response(output) if output else None
        if result is not None:
            result["_project_selection"] = selection.as_dict()
        return result

    def select_projects(self, title: str, description: str) -> Selection:
        return self._scorer.select(title, description or "")

    def _parse_response(self, text: str) -> dict | None:
        data = extract_json(text)
        if data is None:
            logger.warning(f"Failed to parse response as JSON: {(text or '')[:200]}")
            return None
        if not isinstance(data, dict) or "resume" not in data:
            logger.warning(f"Response missing 'resume' key: {str(data)[:200]}")
            return None
        data.setdefault("cover_letter", "")
        data.setdefault("decisions", {})
        return data
