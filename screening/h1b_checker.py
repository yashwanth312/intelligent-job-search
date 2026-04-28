"""H1B sponsor check via h1bdata.info — Phase 7 of the pipeline."""
from __future__ import annotations

import asyncio
import re
import urllib.parse
from datetime import datetime, timezone

import aiohttp

from db.database import Database
from models.job import RawJob

_LEGAL_SUFFIXES_RE = re.compile(
    r"\b(inc|llc|corp|ltd|l\.?p|plc|incorporated|limited|corporation)\b\.?",
    re.IGNORECASE,
)

_CURATED_PREFIXES = ("greenhouse-", "lever-", "ashby-")


class H1BChecker:
    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _normalize(company: str) -> str:
        """Return a canonical cache key for a company name."""
        name = _LEGAL_SUFFIXES_RE.sub("", company)
        name = re.sub(r"[^a-z0-9\s]", "", name.lower())
        return re.sub(r"\s+", " ", name).strip()

    @staticmethod
    def _has_results(html: str) -> bool:
        """Return True if the h1bdata.info HTML table contains at least one data row."""
        if "no data available in table" in html.lower():
            return False
        return bool(re.search(r"<tbody[^>]*>\s*<tr", html, re.IGNORECASE))
