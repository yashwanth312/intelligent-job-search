"""Stage 2: Claude CLI precision screening — profile-aware evaluation."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from models.job import RawJob, ScreenedJob, ScreeningVerdict
from config import SCREENING_BATCH_SIZE, CLAUDE_CLI

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "screening.md"

class Stage2Screen:
    def __init__(self, profile_path: str = "profile.yaml"):
        self.profile_path = profile_path
        self._profile_summary: str | None = None

    def validate_cli(self) -> None:
        """Raise RuntimeError if the Claude CLI binary cannot be located."""
        cli = CLAUDE_CLI
        if not (shutil.which(cli) or Path(cli).is_file()):
            raise RuntimeError(
                f"Claude CLI not found at '{cli}'.\n"
                "Install it:  npm install -g @anthropic-ai/claude-code\n"
                "Then either restart your terminal (so PATH is refreshed) or "
                "add CLAUDE_CLI=/full/path/to/claude to your .env file."
            )

    def _load_profile_summary(self) -> str:
        if self._profile_summary:
            return self._profile_summary
        with open(self.profile_path, encoding="utf-8") as f:
            self._profile_summary = f.read()
        return self._profile_summary

    def screen_batch(
        self,
        jobs: list[RawJob],
        on_progress: Callable[[int], None] | None = None,
    ) -> list[ScreenedJob]:
        all_screened: list[ScreenedJob] = []

        for i in range(0, len(jobs), SCREENING_BATCH_SIZE):
            batch = jobs[i:i + SCREENING_BATCH_SIZE]
            batch_results = self._screen_one_batch(batch)

            result_map = {r["fingerprint"]: r for r in batch_results}
            missing = [j for j in batch if j.fingerprint not in result_map]
            if missing:
                titles = ", ".join(j.title for j in missing)
                logger.warning(
                    f"Stage 2 batch {i // SCREENING_BATCH_SIZE + 1}: "
                    f"{len(result_map)}/{len(batch)} returned — "
                    f"defaulting to MAYBE for: {titles}"
                )
            for job in batch:
                result = result_map.get(job.fingerprint)
                if result:
                    try:
                        screened = ScreenedJob(
                            **job.model_dump(),
                            verdict=ScreeningVerdict(result["verdict"]),
                            confidence=result.get("confidence", 3),
                            reasoning=result.get("reasoning", ""),
                            match_signals=result.get("match_signals", []),
                            risk_flags=result.get("risk_flags", []),
                            suggested_angle=result.get("suggested_angle", ""),
                        )
                        all_screened.append(screened)
                    except Exception as e:
                        logger.warning(f"Failed to create ScreenedJob for {job.fingerprint}: {e}")
                        all_screened.append(self._default_apply(job))
                else:
                    all_screened.append(self._default_maybe(job))

            if on_progress:
                on_progress(1)

        return all_screened

    def _screen_one_batch(self, jobs: list[RawJob]) -> list[dict]:
        prompt_template = PROMPT_PATH.read_text()

        jobs_data = []
        for job in jobs:
            desc = (job.description or "")[:8000]
            jobs_data.append({
                "fingerprint": job.fingerprint,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "description": desc,
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "source": job.source,
                "h1b_sponsor_verified": job.h1b_sponsor_verified,
            })

        prompt = prompt_template.replace(
            "{{profile_summary}}", self._load_profile_summary()
        ).replace(
            "{{jobs_json}}", json.dumps(jobs_data, indent=2)
        )

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.md', delete=False, encoding='utf-8'
            ) as tmp:
                tmp.write(prompt)
                tmp_path = tmp.name

            env = os.environ.copy()
            env["CLAUDECODE"] = "1"
            env.pop("ANTHROPIC_API_KEY", None)  # prevent depleted API key from overriding Max subscription

            with open(tmp_path, encoding='utf-8') as stdin_file:
                result = subprocess.run(
                    [CLAUDE_CLI, "-p", "--output-format", "text", "--model", "claude-sonnet-4-6"],
                    stdin=stdin_file,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=120,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                )
            if result.returncode != 0:
                logger.error(
                    f"Claude CLI error (rc={result.returncode}): "
                    f"stderr={result.stderr[:500]!r}  stdout={result.stdout[:300]!r}"
                )
                return []
            return self._parse_response(result.stdout)
        except subprocess.TimeoutExpired:
            logger.error("Claude CLI timed out")
            return []
        except FileNotFoundError:
            raise RuntimeError(
                f"Claude CLI not found at '{CLAUDE_CLI}'. "
                "Run `npm install -g @anthropic-ai/claude-code` and ensure it is in PATH."
            )
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _parse_response(self, text: str) -> list[dict]:
        text = text.strip()

        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            text = match.group(1).strip()

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            return []
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse Claude response as JSON: {text[:200]}")
            return []

    def _default_apply(self, job: RawJob) -> ScreenedJob:
        return ScreenedJob(
            **job.model_dump(),
            verdict=ScreeningVerdict.APPLY,
            confidence=2,
            reasoning="Claude screening failed — defaulting to APPLY for manual review",
            suggested_angle="",
            risk_flags=[],
        )

    def _default_maybe(self, job: RawJob) -> ScreenedJob:
        return ScreenedJob(
            **job.model_dump(),
            verdict=ScreeningVerdict.MAYBE,
            confidence=2,
            reasoning="Not returned in Claude screening batch — flagged for review",
            suggested_angle="",
            risk_flags=[],
        )
