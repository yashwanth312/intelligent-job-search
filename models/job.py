"""Job data models — RawJob from scrapers, ScreenedJob after AI screening."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, computed_field


class ScreeningVerdict(str, Enum):
    APPLY = "APPLY"
    SKIP = "SKIP"
    MAYBE = "MAYBE"


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
    h1b_sponsor_verified: bool | None = None  # None = not checked / curated source

    @computed_field
    @property
    def fingerprint(self) -> str:
        return f"{self.company.strip().lower()}||{self.title.strip().lower()}"


class ScreenedJob(RawJob):
    """A job after passing through the screening engine."""

    verdict: ScreeningVerdict
    confidence: int = Field(ge=1, le=5)
    reasoning: str
    match_signals: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    suggested_angle: str = ""
