"""Stage 2: Claude CLI precision screening — profile-aware evaluation."""
from __future__ import annotations

import json
import logging
import re
import subprocess
import yaml
from pathlib import Path

from models.job import RawJob, ScreenedJob, ScreeningVerdict
from config import SCREENING_BATCH_SIZE

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "screening.md"


class Stage2Screen:
    def __init__(self, profile_path: str = "profile.yaml"):
        self.profile_path = profile_path
        self._profile_summary: str | None = None

    def _load_profile_summary(self) -> str:
        if self._profile_summary:
            return self._profile_summary

        with open(self.profile_path) as f:
            profile = yaml.safe_load(f)

        personal = profile.get("personal", {})
        parts = [
            f"Name: {personal.get('name', '')}",
            f"Visa: {personal.get('visa', '')}",
            f"Education: {', '.join(e.get('degree', '') + ' @ ' + e.get('school', '') for e in profile.get('education', []))}",
            f"Experience: {', '.join(e.get('company', '') + ' (' + e.get('period', '') + ')' for e in profile.get('experiences', []))}",
            f"Certifications: {', '.join(c.get('name', '') for c in profile.get('certifications', []))}",
        ]

        skills = profile.get("skills", {})
        for category, items in skills.items():
            parts.append(f"Skills ({category}): {', '.join(items[:5])}")

        self._profile_summary = "\n".join(parts)
        return self._profile_summary

    def screen_batch(self, jobs: list[RawJob]) -> list[ScreenedJob]:
        """Screen a batch of jobs using Claude CLI. Returns ScreenedJob list."""
        all_screened: list[ScreenedJob] = []

        for i in range(0, len(jobs), SCREENING_BATCH_SIZE):
            batch = jobs[i:i + SCREENING_BATCH_SIZE]
            batch_results = self._screen_one_batch(batch)

            result_map = {r["fingerprint"]: r for r in batch_results}
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

        return all_screened

    def _screen_one_batch(self, jobs: list[RawJob]) -> list[dict]:
        prompt_template = PROMPT_PATH.read_text()

        jobs_data = []
        for job in jobs:
            desc = (job.description or "")[:3000]
            jobs_data.append({
                "fingerprint": job.fingerprint,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "description": desc,
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "source": job.source,
            })

        prompt = prompt_template.replace(
            "{{profile_summary}}", self._load_profile_summary()
        ).replace(
            "{{jobs_json}}", json.dumps(jobs_data, indent=2)
        )

        try:
            result = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "text"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                logger.error(f"Claude CLI error: {result.stderr}")
                return []
            return self._parse_response(result.stdout)
        except subprocess.TimeoutExpired:
            logger.error("Claude CLI timed out")
            return []
        except FileNotFoundError:
            logger.error("Claude CLI not found — is it installed and in PATH?")
            return []

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
        )

    def _default_maybe(self, job: RawJob) -> ScreenedJob:
        return ScreenedJob(
            **job.model_dump(),
            verdict=ScreeningVerdict.MAYBE,
            confidence=2,
            reasoning="Not returned in Claude screening batch — flagged for review",
            suggested_angle="",
        )
