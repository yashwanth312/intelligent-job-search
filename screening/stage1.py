"""Stage 1: Fast regex-based filtering — no API calls, instant."""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass

from models.job import RawJob
from config import (
    EXCLUDE_TITLE_KEYWORDS, EXCLUDE_DESC_PATTERNS,
    REQUIRE_ONE_OF, SALARY_FLOOR, TITLE_DOMAIN_KEYWORDS,
)

logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    job: RawJob
    passed: bool
    reason: str
    stage: str = "stage1"


class Stage1Filter:

    def filter_job(self, job: RawJob) -> FilterResult:
        title_lower = job.title.lower()
        desc_lower = (job.description or "").lower()
        has_description = bool(job.description and job.description.strip())

        # 1. Title exclusion (word-boundary matching) — always applies
        for kw in EXCLUDE_TITLE_KEYWORDS:
            pattern = r'\b' + re.escape(kw.strip().rstrip('.')) + r'\b'
            if re.search(pattern, title_lower):
                return FilterResult(job=job, passed=False,
                                    reason=f"Title exclusion: '{kw}' matched in '{job.title}'",
                                    stage="stage1_title")

        # 2. Title domain check — at least one domain keyword
        has_domain = any(
            re.search(r'\b' + re.escape(kw) + r'\b', title_lower)
            for kw in TITLE_DOMAIN_KEYWORDS
        )
        if not has_domain:
            return FilterResult(job=job, passed=False,
                                reason=f"No domain keyword in title: '{job.title}'",
                                stage="stage1_title_domain")

        # 3. Salary floor — always applies
        if job.salary_max is not None and job.salary_max < SALARY_FLOOR:
            return FilterResult(job=job, passed=False,
                                reason=f"Salary max ${job.salary_max:,} below floor ${SALARY_FLOOR:,}",
                                stage="stage1_salary")

        # No description = can't screen or generate tailored resume. Reject.
        if not has_description:
            return FilterResult(job=job, passed=False,
                                reason="No description — cannot screen or generate tailored resume",
                                stage="stage1_no_desc")

        # 4. Description hard-stops
        for pattern in EXCLUDE_DESC_PATTERNS:
            if pattern.lower() in desc_lower:
                return FilterResult(job=job, passed=False,
                                    reason=f"Description hard-stop: '{pattern}'",
                                    stage="stage1_desc")

        # 5. Must-have keyword check (title already has domain keyword, so check desc too)
        combined = title_lower + " " + desc_lower
        has_required = any(kw.lower() in combined for kw in REQUIRE_ONE_OF)
        if not has_required:
            return FilterResult(job=job, passed=False,
                                reason="No required keywords found in title or description",
                                stage="stage1_keywords")

        return FilterResult(job=job, passed=True, reason="Passed all Stage 1 filters",
                            stage="stage1_pass")

    def filter_batch(self, jobs: list[RawJob]) -> tuple[list[RawJob], list[FilterResult]]:
        passed: list[RawJob] = []
        rejected: list[FilterResult] = []

        for job in jobs:
            result = self.filter_job(job)
            if result.passed:
                passed.append(job)
            else:
                rejected.append(result)

        logger.info(f"Stage 1: {len(passed)} passed, {len(rejected)} rejected out of {len(jobs)}")
        return passed, rejected
