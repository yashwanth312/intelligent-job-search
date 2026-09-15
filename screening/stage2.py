"""Stage 2: Claude CLI precision screening — profile-aware evaluation."""
from __future__ import annotations

import json
import logging
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from models.job import RawJob, ScreenedJob, ScreeningVerdict
from config import (
    SCREENING_BATCH_SIZE, SCREENING_MAX_WORKERS, CLAUDE_CLI,
    SPONSORSHIP_FILTER_ENABLED, STAGE2_MODEL, STAGE2_TIMEOUT,
    STAGE2_THINKING_BUDGET_TOKENS,
)
from generation.claude_cli import run_claude, extract_json

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "screening.md"

# Split point: everything before this heading (profile + strategy + confidence
# scale + sponsorship policy + output format) is constant for the whole run
# and is sent once via --system-prompt-file so it's cached server-side instead
# of re-billed as cache-creation on every batch. Only the jobs list itself is
# piped per call.
_JOBS_SECTION_START = "## Jobs to Screen"

# Defensive output caps — belt-and-suspenders alongside the prompt's own
# "one sentence" / list-length guidance, so a verbose response never balloons
# a Sheets cell or output tokens.
_MAX_REASONING_CHARS = 300
_MAX_LIST_ITEMS = 5

# Filled into the screening prompt's {{sponsorship_policy}} slot. Governed by
# config.SPONSORSHIP_FILTER_ENABLED so the screening posture matches the rest
# of the pipeline with a single toggle.
_SPONSORSHIP_POLICY_ON = (
    "- If the job description explicitly states the company will NOT provide visa "
    "sponsorship (any phrasing: 'no sponsorship', 'will not sponsor', 'cannot sponsor', "
    "'must be authorized to work without sponsorship', 'sponsorship not available', etc.), "
    "verdict MUST be SKIP regardless of other signals — treat as a hard disqualifier.\n"
    "- If h1b_sponsor_verified is False but the JD does NOT explicitly deny sponsorship: "
    "reduce confidence by 1 (minimum 1). Do not add to risk_flags — "
    "sponsorship has its own sheet column."
)
_SPONSORSHIP_POLICY_OFF = (
    "- Sponsorship is NOT a scoring factor. The candidate is currently "
    "work-authorized and does not require sponsorship. Ignore "
    "h1b_sponsor_verified entirely: do NOT reduce confidence, add risk flags, "
    "or lower the verdict for sponsorship, visa, or \"no sponsorship\" "
    "language in the JD."
)

class Stage2Screen:
    def __init__(self, profile_path: str = "profile.yaml"):
        self.profile_path = profile_path
        self._profile: str | None = None
        self._system_prompt: str | None = None

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

    def _load_profile(self) -> str:
        if self._profile:
            return self._profile
        with open(self.profile_path, encoding="utf-8") as f:
            self._profile = f.read()
        return self._profile

    def _build_system_prompt(self) -> str:
        """Profile + strategy + confidence scale + sponsorship policy + output
        format — everything except the jobs list itself. Memoized: constant
        for the whole run (profile and the sponsorship-policy toggle don't
        change between batches), so this is built once and reused
        byte-identical on every call — required for the server-side prompt
        cache to actually hit.
        """
        if self._system_prompt is not None:
            return self._system_prompt
        template = PROMPT_PATH.read_text()
        before, _rest = template.split(_JOBS_SECTION_START, 1)
        sponsorship_policy = (
            _SPONSORSHIP_POLICY_ON if SPONSORSHIP_FILTER_ENABLED
            else _SPONSORSHIP_POLICY_OFF
        )
        self._system_prompt = (
            before
            .replace("{{profile}}", self._load_profile())
            .replace("{{sponsorship_policy}}", sponsorship_policy)
        )
        return self._system_prompt

    def screen_batch(
        self,
        jobs: list[RawJob],
        on_progress: Callable[[int], None] | None = None,
        max_workers: int = SCREENING_MAX_WORKERS,
    ) -> list[ScreenedJob]:
        """Screen all jobs, SCREENING_BATCH_SIZE at a time, running up to
        `max_workers` batches concurrently.

        Batches are independent, stateless Claude CLI calls (each writes its
        own temp files and spawns its own subprocess), so this is the same
        concurrency pattern generate_materials.py already uses safely for
        resume generation. Batches ran strictly sequentially until 2026-09-09,
        which made Stage 2 the dominant chunk of run time once scraping and
        generation got fast — see SCREENING_MAX_WORKERS in config.py.

        Results are reassembled in original job order regardless of which
        batch finishes first, so output is identical to the old sequential
        version — only wall-clock time changes.

        Cache-warming: when there are MORE batches than `max_workers` (i.e.
        there will be a second wave), batch 0 is run alone before the rest
        are fanned out. The system prompt (profile + strategy, built once
        and byte-identical for the whole run — see _build_system_prompt)
        only becomes server-side cache-*readable* after a call using it
        completes; submitting every batch at once means up to `max_workers`
        of them race to go first, and each pays the full cache-*creation*
        price for the same ~10-14K-token prompt instead of one write + many
        cheap reads. Measured on 2026-09-11 usage logs: cache_creation and
        cache_read tokens were roughly equal per run, meaning most batches
        were still missing the cache. Seeding with one call first turns that
        into a single miss. Skipped when all batches fit in one wave anyway
        (`len(batches) <= max_workers`) — there's no second wave to benefit,
        so seeding would only add a serial ~100-150s to a run that was
        already fully concurrent.
        """
        batches = [jobs[i:i + SCREENING_BATCH_SIZE] for i in range(0, len(jobs), SCREENING_BATCH_SIZE)]
        if not batches:
            return []

        results_by_batch: dict[int, list[ScreenedJob]] = {}
        progress_lock = threading.Lock()

        def _run_one(batch_num: int, batch: list[RawJob]) -> tuple[int, list[ScreenedJob]]:
            batch_results = self._screen_one_batch(batch)
            screened = self._map_batch_results(batch_num, batch, batch_results)
            if on_progress:
                with progress_lock:
                    on_progress(1)
            return batch_num, screened

        workers = max(1, min(max_workers, len(batches)))
        remaining = list(enumerate(batches))

        if len(batches) > workers:
            batch_num, screened = _run_one(*remaining[0])
            results_by_batch[batch_num] = screened
            remaining = remaining[1:]

        if remaining:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="stage2-screen") as executor:
                futures = [executor.submit(_run_one, i, batch) for i, batch in remaining]
                for future in as_completed(futures):
                    batch_num, screened = future.result()
                    results_by_batch[batch_num] = screened

        all_screened: list[ScreenedJob] = []
        for i in range(len(batches)):
            all_screened.extend(results_by_batch[i])
        return all_screened

    def _map_batch_results(
        self, batch_num: int, batch: list[RawJob], batch_results: list[dict],
    ) -> list[ScreenedJob]:
        """Map one batch's raw Claude results onto ScreenedJob, defaulting to
        MAYBE for anything Claude didn't return. Pure function of one batch —
        safe to call from any thread.
        """
        # Key by the batch-position `index` Claude echoes back — robust to
        # any drift between our fingerprint string and what Claude returns
        # (whitespace/casing/truncation), which previously caused a
        # handful of silent MAYBE-defaults per run. Fall back to matching
        # on fingerprint for any response that omits `index`.
        by_index = {
            r["index"]: r for r in batch_results
            if isinstance(r.get("index"), int) and 0 <= r["index"] < len(batch)
        }
        by_fingerprint = {r["fingerprint"]: r for r in batch_results if "fingerprint" in r}

        result_map = {}
        for idx, job in enumerate(batch):
            result_map[job.fingerprint] = by_index.get(idx) or by_fingerprint.get(job.fingerprint)

        missing = [j for j in batch if not result_map.get(j.fingerprint)]
        if missing:
            titles = ", ".join(j.title for j in missing)
            logger.warning(
                f"Stage 2 batch {batch_num + 1}: "
                f"{len(batch) - len(missing)}/{len(batch)} returned — "
                f"defaulting to MAYBE for: {titles}"
            )

        screened_batch: list[ScreenedJob] = []
        for job in batch:
            result = result_map.get(job.fingerprint)
            if result:
                # Claude is asked for confidence 1-5 (see prompts/screening.md)
                # but occasionally returns an out-of-range value (e.g. 0 for a
                # "definitely not" case it doesn't have a scale point for).
                # That's a real, informative verdict, not a parse failure --
                # clamp it into range rather than letting ScreenedJob's
                # validator reject the whole result and fall through to the
                # except branch below, which used to mistake this for a
                # screening failure and force verdict=APPLY on a job Claude
                # was actively trying to reject.
                raw_confidence = result.get("confidence", 3)
                try:
                    clamped_confidence = max(1, min(5, int(raw_confidence)))
                except (TypeError, ValueError):
                    clamped_confidence = 3
                try:
                    screened = ScreenedJob(
                        **job.model_dump(),
                        verdict=ScreeningVerdict(result["verdict"]),
                        confidence=clamped_confidence,
                        reasoning=(result.get("reasoning") or "")[:_MAX_REASONING_CHARS],
                        match_signals=(result.get("match_signals") or [])[:_MAX_LIST_ITEMS],
                        risk_flags=(result.get("risk_flags") or [])[:_MAX_LIST_ITEMS],
                        suggested_angle=result.get("suggested_angle", ""),
                        interview_likelihood=result.get("interview_likelihood"),
                    )
                    screened_batch.append(screened)
                except Exception as e:
                    # A result was returned but still didn't fit the schema
                    # (e.g. an unrecognized verdict string) -- this is
                    # genuinely ambiguous, so flag it for manual review rather
                    # than assuming the job is worth applying to.
                    logger.warning(f"Failed to create ScreenedJob for {job.fingerprint}: {e}")
                    screened_batch.append(self._default_maybe(job))
            else:
                screened_batch.append(self._default_maybe(job))

        return screened_batch

    def _screen_one_batch(self, jobs: list[RawJob]) -> list[dict]:
        template = PROMPT_PATH.read_text()
        _before, jobs_section = template.split(_JOBS_SECTION_START, 1)

        jobs_data = []
        for idx, job in enumerate(jobs):
            desc = (job.description or "")[:8000]
            jobs_data.append({
                "index": idx,
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

        dynamic_prompt = (
            _JOBS_SECTION_START + jobs_section
        ).replace("{{jobs_json}}", json.dumps(jobs_data, indent=2))

        output = run_claude(
            dynamic_prompt, model=STAGE2_MODEL, timeout=STAGE2_TIMEOUT, label="Stage 2 screening",
            purpose="screening", system_prompt=self._build_system_prompt(),
            thinking_budget_tokens=STAGE2_THINKING_BUDGET_TOKENS,
        )
        if output is None:
            return []
        return self._parse_response(output)

    def _parse_response(self, text: str) -> list[dict]:
        data = extract_json(text)
        if isinstance(data, list):
            return data
        if data is None:
            logger.warning(f"Failed to parse Claude response as JSON: {(text or '')[:200]}")
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
