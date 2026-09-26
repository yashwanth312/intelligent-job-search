"""Stage 1: Fast regex-based filtering — no API calls, instant."""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass

from models.job import RawJob
from config import (
    EXCLUDE_TITLE_KEYWORDS, EXCLUDE_DESC_PATTERNS,
    REQUIRE_ONE_OF, SALARY_FLOOR, TITLE_DOMAIN_KEYWORDS,
    IT_IDENTITY_TITLE_KEYWORDS, IT_IDENTITY_SECURITY_BLOCKERS,
    SPONSORSHIP_DESC_PATTERNS, SPONSORSHIP_FILTER_ENABLED,
    EXCLUDE_LOCATION_PATTERNS, MIN_YOE_HARD_STOP,
)

logger = logging.getLogger(__name__)


def _any_word(keywords: list[str], text: str) -> bool:
    return any(re.search(r'\b' + re.escape(kw) + r'\b', text) for kw in keywords)


def title_admission(title: str) -> str | None:
    """Which title family admits `title`: "core" (TITLE_DOMAIN_KEYWORDS),
    "it_identity" (IT_IDENTITY_TITLE_KEYWORDS on a title with no security
    word), or None. Recorded per application so the IT/identity family's
    callback rate can be measured separately."""
    title_lower = title.lower()
    if _any_word(TITLE_DOMAIN_KEYWORDS, title_lower):
        return "core"
    if (_any_word(IT_IDENTITY_TITLE_KEYWORDS, title_lower)
            and not _any_word(IT_IDENTITY_SECURITY_BLOCKERS, title_lower)):
        return "it_identity"
    return None


def _has_title_domain(title_lower: str) -> bool:
    return title_admission(title_lower) is not None

# Effective description hard-stops. The sponsorship-availability patterns are
# folded in only when the master toggle is on; while it's off, a "we don't
# sponsor" JD is kept (the candidate is work-authorized). See config.py.
_DESC_HARD_STOPS = list(EXCLUDE_DESC_PATTERNS)
if SPONSORSHIP_FILTER_ENABLED:
    _DESC_HARD_STOPS += SPONSORSHIP_DESC_PATTERNS

# ── Years-of-experience hard-stop (see config.MIN_YOE_HARD_STOP) ─────────
# Numeral (1-2 digits) or number-word, so "5+ years" and "five+ years" both
# resolve to a comparable int.
_YOE_NUM_WORDS = {
    "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10,
}
_YOE_NUM_PATTERN = r'(?:\d{1,2}|' + '|'.join(_YOE_NUM_WORDS) + r')'

# "5+ years" / "five or more years"
_YOE_PLUS_RE = re.compile(
    rf'\b({_YOE_NUM_PATTERN})\s*(?:\+|or more)\s*years?\b', re.I
)
# "at least 5 years" / "minimum 5 years" / "minimum of 5 years"
_YOE_ATLEAST_RE = re.compile(
    rf'\b(?:at least|minimum(?:\s+of)?)\s+({_YOE_NUM_PATTERN})\s*years?\b', re.I
)
# "4-6 years" / "4 to 6 years" — only the lower bound has to clear the
# threshold (a range starting below it, e.g. "2-5 years", isn't a hard
# requirement of the higher number). Tolerates a plain hyphen here; the
# markdown-escaped form ("4\-6 years") is normalized before matching — see
# _normalize_desc_dashes.
_YOE_RANGE_RE = re.compile(
    rf'\b({_YOE_NUM_PATTERN})\s*(?:-|to)\s*{_YOE_NUM_PATTERN}\+?\s*years?\b', re.I
)
# Bare "N years [of] [...] experience" — no "+"/"minimum"/"at least"
# qualifier at all. The single most common real-world phrasing and
# previously uncovered by any pattern.
_YOE_BARE_RE = re.compile(
    rf'\b({_YOE_NUM_PATTERN})\+?\s*years?\s+(?:of\s+)?(?:[a-z][a-z\-]*\s+){{0,3}}experience\b',
    re.I,
)
# Guards against the BARE pattern matching the upper bound of a range whose
# lower bound is below threshold, e.g. "2-5 years of experience" — the
# range regex already (correctly) leaves that alone, so BARE must not
# re-flag its own "5 years of experience" tail as a standalone requirement.
_YOE_RANGE_PREFIX_RE = re.compile(r'\d\s*(?:-|to)\s*$', re.I)


def _yoe_value(token: str) -> int:
    token = token.strip().lower()
    if token in _YOE_NUM_WORDS:
        return _YOE_NUM_WORDS[token]
    try:
        value = int(token)
    except ValueError:
        return 0
    # A range whose en dash was dropped during scraping: "3–5 years" arrives
    # as "35 years". Read an implausible two-digit value with ascending digits
    # as that range's lower bound, like _YOE_RANGE_RE does. NYU Langone's
    # "Engineer II, Gen AI" (assessment invite) was hard-stopped on exactly this.
    if value >= 16 and token[0] < token[1]:
        return int(token[0])
    return value


def _normalize_desc_dashes(text: str) -> str:
    """Collapse markdown-escaped hyphens ("4\\-6" -> "4-6") so the range
    pattern matches jobspy's Markdown-formatted LinkedIn/Indeed descriptions,
    which backslash-escape every literal hyphen."""
    return text.replace('\\-', '-')


def _find_yoe_hard_stop(desc_lower: str) -> str | None:
    """Return a reason string if the (dash-normalized, lowercased)
    description contains a YOE requirement >= MIN_YOE_HARD_STOP, else None."""
    desc_lower = _normalize_desc_dashes(desc_lower)

    for regex in (_YOE_PLUS_RE, _YOE_ATLEAST_RE, _YOE_RANGE_RE):
        m = regex.search(desc_lower)
        if m and _yoe_value(m.group(1)) >= MIN_YOE_HARD_STOP:
            return f"YOE requirement: '{m.group(0).strip()}'"

    for m in _YOE_BARE_RE.finditer(desc_lower):
        if _yoe_value(m.group(1)) < MIN_YOE_HARD_STOP:
            continue
        if _YOE_RANGE_PREFIX_RE.search(desc_lower[max(0, m.start() - 6):m.start()]):
            continue  # upper bound of an "A-B years" range — see guard comment above
        preceding = desc_lower[max(0, m.start() - 15):m.start()]
        if "over" in preceding:
            # "...with over 26 years of experience, we consistently
            # deliver..." — company-history marketing copy, not a personal
            # requirement. Cheap heuristic, not airtight, but matches the
            # false-positive shape actually observed in scraped JDs.
            continue
        return f"YOE requirement: '{m.group(0).strip()}'"

    return None


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
        location_lower = (job.location or "").lower()

        # 0. Location exclusion — drop non-US postings before anything else
        for pattern in EXCLUDE_LOCATION_PATTERNS:
            if pattern in location_lower:
                return FilterResult(job=job, passed=False,
                                    reason=f"Non-US location: '{job.location}'",
                                    stage="stage1_location")

        # 1. Title exclusion (word-boundary matching) — always applies
        for kw in EXCLUDE_TITLE_KEYWORDS:
            pattern = r'\b' + re.escape(kw.strip().rstrip('.')) + r'\b'
            if re.search(pattern, title_lower):
                return FilterResult(job=job, passed=False,
                                    reason=f"Title exclusion: '{kw}' matched in '{job.title}'",
                                    stage="stage1_title")

        # 2. Title domain check — at least one domain keyword must appear in the title
        if not _has_title_domain(title_lower):
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

        # 4. Description hard-stops (clearance/citizenship + sponsorship
        # availability, when enabled)
        for pattern in _DESC_HARD_STOPS:
            if pattern.lower() in desc_lower:
                return FilterResult(job=job, passed=False,
                                    reason=f"Description hard-stop: '{pattern}'",
                                    stage="stage1_desc")

        # 4b. Years-of-experience hard-stop — see config.MIN_YOE_HARD_STOP.
        yoe_reason = _find_yoe_hard_stop(desc_lower)
        if yoe_reason:
            return FilterResult(job=job, passed=False, reason=yoe_reason,
                                stage="stage1_desc")

        # 5. Must-have keyword check — title + description combined (word-boundary).
        # Requires 2+ distinct matches so single-keyword tangents (industrial
        # automation, EPC telecom, substation) don't reach Stage 2.
        combined = title_lower + " " + desc_lower
        match_count = sum(
            1 for kw in REQUIRE_ONE_OF
            if re.search(r'\b' + re.escape(kw.lower()) + r'\b', combined)
        )
        if match_count < 3:
            return FilterResult(job=job, passed=False,
                                reason=f"Only {match_count}/3 required keywords found",
                                stage="stage1_keywords")

        return FilterResult(job=job, passed=True, reason="Passed all Stage 1 filters",
                            stage="stage1_pass")

    def filter_titles_only(self, jobs: list[RawJob]) -> tuple[list[RawJob], list[FilterResult]]:
        """Run only title exclusion + domain check on jobs that have no description.

        Used for no_desc_jobs before they reach the Daily tab so that obviously
        wrong titles (senior, intern, unrelated domain) are routed to Audit instead.
        """
        passed: list[RawJob] = []
        rejected: list[FilterResult] = []

        for job in jobs:
            title_lower = job.title.lower()

            for kw in EXCLUDE_TITLE_KEYWORDS:
                pattern = r'\b' + re.escape(kw.strip().rstrip('.')) + r'\b'
                if re.search(pattern, title_lower):
                    rejected.append(FilterResult(
                        job=job, passed=False,
                        reason=f"Title exclusion: '{kw}' matched in '{job.title}'",
                        stage="stage1_title",
                    ))
                    break
            else:
                if not _has_title_domain(title_lower):
                    rejected.append(FilterResult(
                        job=job, passed=False,
                        reason=f"No domain keyword in title: '{job.title}'",
                        stage="stage1_title_domain",
                    ))
                else:
                    passed.append(job)

        logger.info(
            f"Stage 1 (title-only): {len(passed)} passed, {len(rejected)} rejected "
            f"out of {len(jobs)} no-description jobs"
        )
        return passed, rejected

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
