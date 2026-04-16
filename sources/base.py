"""Base interface for all source adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from models.job import RawJob


@dataclass
class SourceResult:
    jobs: list[RawJob] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class SourceAdapter(ABC):
    name: str = "base"

    @abstractmethod
    async def scrape(self, titles: list[str], locations: list[str]) -> SourceResult:
        ...
