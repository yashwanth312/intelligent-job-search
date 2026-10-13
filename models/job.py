"""Job data models — RawJob from scrapers, ScreenedJob after AI screening."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, computed_field


class RawJob(BaseModel):
    """A job listing as returned by any source adapter."""

    title: str
    company: str
    location: str
    description: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    url: str
    source: str  # e.g. "greenhouse-anthropic", "hn-apr2026", "linkedin"
    scraped_at: datetime = Field(default_factory=datetime.now)
    posted_at: datetime | None = None  # When the company actually posted the job (UTC)
    h1b_sponsor_verified: bool | None = None  # None = lookup errored or timed out

    @computed_field
    @property
    def fingerprint(self) -> str:
        return f"{self.company.strip().lower()}||{self.title.strip().lower()}"


class ScreenedJob(RawJob):
    """A job after passing through the screening engine.

    There is no verdict (APPLY/MAYBE/SKIP was removed 2026-10-03): confidence,
    interview_likelihood and risk_flags are the whole screening output, and
    config.DAILY_MIN_CONFIDENCE decides what reaches the Daily tab."""

    # 1-5 fit score. None = not scored (Stage 2 failed for this job, or it had
    # no description) — renders blank and is never mistaken for a real score.
    confidence: int | None = Field(default=None, ge=1, le=5)
    reasoning: str
    match_signals: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    suggested_angle: str = ""
    # Probability (0-100) of landing an interview after the resume is
    # customized per suggested_angle. None when not assessed by Claude
    # (e.g. no-description fallback jobs) — renders as a blank cell.
    interview_likelihood: int | None = Field(default=None, ge=0, le=100)
