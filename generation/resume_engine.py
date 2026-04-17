"""Resume + cover letter generation via Claude Code CLI."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

import yaml

from config import YOUR_NAME, YOUR_EMAIL, YOUR_PHONE, CLAUDE_CLI

logger = logging.getLogger(__name__)

RESUME_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "resume.md"
CL_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "cover_letter.md"


class ResumeEngine:
    def __init__(self, profile_path: str = "profile.yaml"):
        with open(profile_path) as f:
            self._profile_raw = f.read()
        self._profile = yaml.safe_load(self._profile_raw)

    def generate(
        self, company: str, title: str, location: str,
        description: str, source: str, screening_notes: str = "",
    ) -> dict | None:
        """Generate resume + cover letter for one job. Returns parsed dict or None."""
        resume_data = self._generate_resume(
            company, title, location, description, source, screening_notes,
        )
        if not resume_data:
            return None

        cover_letter_data = self._generate_cover_letter(
            company, title, location, description,
            resume_data.get("decisions", {}).get("angle", ""),
        )

        resume_data["cover_letter"] = cover_letter_data.get("cover_letter", "") if cover_letter_data else ""
        return resume_data

    def _generate_resume(
        self, company: str, title: str, location: str,
        description: str, source: str, screening_notes: str,
    ) -> dict | None:
        template = RESUME_PROMPT_PATH.read_text()
        prompt = (
            template
            .replace("{{profile_yaml}}", self._profile_raw)
            .replace("{{company}}", company)
            .replace("{{title}}", title)
            .replace("{{location}}", location)
            .replace("{{source}}", source)
            .replace("{{screening_notes}}", screening_notes)
            .replace("{{description}}", (description or "")[:4000])
        )
        output = self._invoke_claude(prompt)
        return self._parse_response(output) if output else None

    def _generate_cover_letter(
        self, company: str, title: str, location: str,
        description: str, resume_angle: str,
    ) -> dict | None:
        personal = self._profile.get("personal", {})
        profile_summary = f"Name: {personal.get('name', '')}\nVisa: {personal.get('visa', '')}"

        template = CL_PROMPT_PATH.read_text()
        prompt = (
            template
            .replace("{{profile_summary}}", profile_summary)
            .replace("{{company}}", company)
            .replace("{{title}}", title)
            .replace("{{location}}", location)
            .replace("{{description}}", (description or "")[:4000])
            .replace("{{resume_angle}}", resume_angle)
        )
        output = self._invoke_claude(prompt)
        return self._parse_response(output) if output else None

    def _invoke_claude(self, prompt: str) -> str | None:
        try:
            result = subprocess.run(
                [CLAUDE_CLI, "-p", prompt, "--output-format", "text"],
                capture_output=True, text=True, timeout=180,
            )
            if result.returncode != 0:
                logger.error(f"Claude CLI error: {result.stderr[:500]}")
                return None
            return result.stdout
        except subprocess.TimeoutExpired:
            logger.error("Claude CLI timed out during resume generation")
            return None
        except FileNotFoundError:
            logger.error("Claude CLI not found")
            return None

    def _parse_response(self, text: str) -> dict | None:
        text = text.strip()
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            text = match.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse response: {text[:200]}")
            return None
