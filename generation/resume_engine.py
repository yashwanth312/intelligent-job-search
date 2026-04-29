"""Resume + cover letter generation via Claude Code CLI.

A SINGLE Claude CLI call returns both the structured resume JSON and the
cover letter text. The prompt is piped via stdin (not argv) so neither the
full profile.yaml nor the full job description hits Windows' ~32KB argv
limit. ANTHROPIC_API_KEY is purged from the subprocess env so the call
always uses the user's Max subscription via the Claude CLI session, never
pay-per-token API credits.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

import yaml

from config import CLAUDE_CLI

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "application_materials.md"


class ResumeEngine:
    def __init__(self, profile_path: str = "profile.yaml"):
        with open(profile_path) as f:
            self._profile_raw = f.read()
        self._profile = yaml.safe_load(self._profile_raw)

    def generate(
        self, company: str, title: str, location: str,
        description: str, source: str, screening_notes: str = "",
    ) -> dict | None:
        """Generate resume + cover letter for one job in a single Claude call.

        Returns a dict shaped like:
          {"resume": {...}, "decisions": {...}, "cover_letter": "..."}
        or None if the call or parse failed.
        """
        template = PROMPT_PATH.read_text(encoding="utf-8")
        prompt = (
            template
            .replace("{{profile_yaml}}", self._profile_raw)
            .replace("{{company}}", company)
            .replace("{{title}}", title)
            .replace("{{location}}", location)
            .replace("{{source}}", source)
            .replace("{{screening_notes}}", screening_notes)
            .replace("{{description}}", description or "")
        )
        output = self._invoke_claude(prompt)
        return self._parse_response(output) if output else None

    def _invoke_claude(self, prompt: str) -> str | None:
        """Invoke Claude CLI with prompt on stdin. Forces Max subscription path."""
        env = os.environ.copy()
        env["CLAUDECODE"] = "1"
        env.pop("ANTHROPIC_API_KEY", None)  # force Max subscription, not pay-per-token API

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(prompt)
                tmp_path = tmp.name

            with open(tmp_path, encoding="utf-8") as stdin_file:
                result = subprocess.run(
                    [CLAUDE_CLI, "-p", "--output-format", "text"],
                    stdin=stdin_file,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=300,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                )
            if result.returncode != 0:
                logger.error(
                    f"Claude CLI error (rc={result.returncode}): "
                    f"stderr={result.stderr[:500]!r}  stdout={result.stdout[:300]!r}"
                )
                return None
            return result.stdout
        except subprocess.TimeoutExpired:
            logger.error("Claude CLI timed out during materials generation")
            return None
        except FileNotFoundError:
            logger.error(f"Claude CLI not found at '{CLAUDE_CLI}'")
            return None
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _parse_response(self, text: str) -> dict | None:
        text = text.strip()
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            text = match.group(1).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse response as JSON: {text[:200]}")
            return None

        if not isinstance(data, dict) or "resume" not in data:
            logger.warning(f"Response missing 'resume' key: {str(data)[:200]}")
            return None
        data.setdefault("cover_letter", "")
        data.setdefault("decisions", {})
        return data
