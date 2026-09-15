"""H1B sponsor check via h1bdata.info — Phase 5 of the pipeline.

How h1bdata.info actually matches
---------------------------------
The `em=` parameter is a PREFIX search over the legal employer name as it
appears on the LCA filing, not a fuzzy or substring search. Verified by probe:

    em=amazon web services  -> AMAZON WEB SERVICES INC        (hit)
    em=accenture            -> ACCENTURE INFRASTRUCTURE ...   (hit)
    em=accenture federal    -> (no rows — no filer starts with that)
    em=at t                 -> AT&T ... (hit; "&" must become a SPACE)
    em=att                  -> (no rows)
    em=amazoncom            -> AMAZONCOM SERVICES LLC         (hit; "." is DROPPED)

Two consequences drive this module's design:

1. Job boards publish decorated company strings — "Amazon Web Services (AWS)",
   "NVIDIA AI", "Walmart Global Tech", "Hakkoda, an IBM Company". None of those
   is the prefix of any legal filer name, so a single literal query misses and
   the employer is recorded as a non-sponsor. That one miss then drops every
   posting from that company. "Amazon Web Services (AWS)" alone accounted for
   3,139 dropped postings before this was fixed.

2. Punctuation is not uniform: dots are dropped by h1bdata ("amazoncom") while
   ampersands are spaces ("at t"). Normalizing all punctuation the same way
   guarantees a miss on one class or the other, so both variants are tried.

The filter is therefore deliberately asymmetric. A false negative silently and
permanently removes an employer from the pipeline; a false positive costs one
Stage 2 screen, which then rejects it anyway. Every ambiguity resolves toward
KEEP.
"""
from __future__ import annotations

import asyncio
import re
import urllib.parse
from datetime import datetime, timezone

import aiohttp

from db.database import Database
from models.job import RawJob

# Trailing legal-entity suffixes. Stripped only from the END of a name (possibly
# repeated, e.g. "Foo Holdings Inc"), never mid-string — "Corporation Service
# Company" must not lose its first word.
_TRAILING_SUFFIX_RE = re.compile(
    r"[\s,]+(?:inc|llc|l\s*l\s*c|corp|corporation|incorporated|ltd|limited|co|"
    r"plc|llp|pllc|lp|gmbh|ag|nv|bv|sas|sa|srl|spa|pvt|pte|pty|kk|ab|oy|as)\.?$",
    re.IGNORECASE,
)

# Marketing decoration job boards append to the employer field. Everything from
# the marker onward is dropped: "Hakkoda, an IBM Company" -> "Hakkoda",
# "N2 Lab | Oracle NetSuite Alliance Partner" -> "N2 Lab".
_TAGLINE_RE = re.compile(
    r"\s*(?:\||,\s*(?:an?|part of)\s+|\s+-\s+|\s+–\s+|\s+—\s+).*$",
    re.IGNORECASE,
)

_PARENTHETICAL_RE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")

# A name made only of these carries no employer identity ("Inc.", "LLC"). The
# trailing-suffix regex deliberately refuses to consume a whole name, so this
# catches the degenerate case instead.
_LEGAL_SUFFIX_WORDS = frozenset({
    "inc", "llc", "corp", "corporation", "incorporated", "ltd", "limited",
    "co", "plc", "llp", "pllc", "lp", "gmbh", "ag", "nv", "bv", "sa", "sas",
    "srl", "spa", "pvt", "pte", "pty", "kk", "ab", "oy", "as", "company",
})

# Generic qualifiers a job board bolts onto a parent brand. Peeled off the end
# one at a time to walk back toward the filing entity: "NTT Data North America"
# -> "NTT Data", "Accenture Federal Services" -> "Accenture", "NVIDIA AI" -> "NVIDIA".
_GENERIC_TAIL_TOKENS = frozenset({
    "ai", "ml", "cloud", "digital", "tech", "technologies", "technology",
    "labs", "lab", "studios", "studio", "services", "service", "solutions",
    "systems", "group", "groups", "global", "us", "usa", "america", "americas",
    "north", "south", "federal", "international", "consulting", "consultancy",
    "partners", "ventures", "media", "network", "networks", "software",
    "engineering", "products", "product", "platform", "platforms",
    "enterprises", "enterprise", "industries", "worldwide", "team", "careers",
    "recruiting", "talent", "staffing", "research", "development",
})

# Never let a root this generic inherit a parent brand's verdict, and never
# query it on its own — it would match an unrelated filer.
_UNSAFE_ROOTS = frozenset({
    "the", "and", "new", "one", "first", "national", "american", "united",
    "general", "global", "premier", "advanced", "applied", "integrated",
    "innovative", "creative", "digital", "data", "cloud", "tech", "talent",
    "stealth", "confidential", "undisclosed", "various", "multiple", "client",
    "jobs", "via", "hiring", "recruiting", "staffing", "consulting", "group",
    "solutions", "services", "systems", "partners", "labs", "studio", "team",
    # Corporate filler that heads thousands of unrelated filers.
    "corporation", "corporate", "company", "holdings", "international",
    "associates", "enterprise", "enterprises", "industries", "management",
    "capital", "ventures", "media", "network", "networks", "software",
    "technology", "technologies", "engineering", "science", "sciences",
    "health", "healthcare", "financial", "finance", "insurance", "bank",
    "energy", "security", "research", "institute", "university", "center",
    "centre", "association", "foundation", "prime", "core", "next", "smart",
})

# Shortest token allowed as a standalone query or an inheritance root. Three
# characters would let "ibm" or "n2" match arbitrary filers; four keeps real
# short brands (KPMG, Okta, Dell, Visa, eBay) reachable.
_MIN_BARE_ROOT_LEN = 4
_MIN_INHERIT_ROOT_LEN = 4

# Direct-ATS boards skip the sponsor check entirely.
#
# The original reason was that the board list was hand-curated. That stopped
# being true on 2026-09-13, when bulk discovery took it from 176 boards to
# ~1,030. The exemption survives on measurement instead: sampling the company
# names on both populations through this checker gives
#
#     auto-discovered boards   n=220   85.0% verified sponsors
#     hand-curated boards      n=102   81.4% verified sponsors
#
# Statistically the same pool, so "curated" was never what made these safe.
# Running the check here would remove ~15% of a small, high-quality pool, and a
# good share of that 15% is name-matching artifact rather than a real
# non-sponsor — short or generic company names ("Arch", "Fin", "Capital",
# "Array", "Zip") cannot prefix-match a legal filer, and early-stage startups
# have no filings yet whether or not they would sponsor.
#
# The filter earns its keep on the OTHER sources: of 89,836 all-time
# stage_h1b drops, 87,134 (97%) were LinkedIn. That is what it is for — a
# keyword search surfaces thousands of arbitrary employers, whereas a board
# list is a set of companies chosen on purpose.
_CURATED_PREFIXES = ("greenhouse-", "lever-", "ashby-")

# Cap on bytes read per response. A hit on a large employer can be an 8 MB page,
# but the results table starts within the first ~60 KB (a miss page is ~60 KB
# in total), so reading past 1 MB only burns bandwidth.
_MAX_READ_BYTES = 1_048_576

# Bound on how many query forms are tried per company before concluding "no
# filings". Each form costs one request per year checked.
_MAX_QUERY_FORMS = 4


class H1BChecker:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._verified_keys: set[str] = set()

    # ── name handling ─────────────────────────────────────

    @staticmethod
    def _clean(company: str) -> str:
        """Strip board decoration down to the bare company name."""
        name = _PARENTHETICAL_RE.sub(" ", company)
        name = _TAGLINE_RE.sub("", name)
        name = re.sub(r"\s+", " ", name).strip(" ,.-|")
        # Suffixes can stack ("Foo Holdings Ltd"); peel until stable.
        for _ in range(3):
            stripped = _TRAILING_SUFFIX_RE.sub("", name).strip(" ,.")
            if stripped == name or not stripped:
                break
            name = stripped
        return name

    @staticmethod
    def _tokens(name: str, *, dots_as_space: bool) -> list[str]:
        """Lowercase a cleaned name into query tokens.

        `dots_as_space` picks between h1bdata's two punctuation conventions:
        dots dropped ("amazon.com" -> "amazoncom") or separated
        ("amazon.com" -> "amazon com"). Ampersands and slashes are always
        separators — "AT&T" only matches as "at t".
        """
        s = name.lower()
        s = re.sub(r"[&/+]", " ", s)
        s = s.replace(".", " ") if dots_as_space else s.replace(".", "")
        s = re.sub(r"[^a-z0-9\s]", " ", s)
        tokens = [t for t in s.split() if t]
        if tokens and all(t in _LEGAL_SUFFIX_WORDS for t in tokens):
            return []  # "Inc." — no employer identity to query
        return tokens

    @classmethod
    def _normalize(cls, company: str) -> str:
        """Return a canonical cache key for a company name.

        Keyed on the cleaned name so that decorated variants of one employer
        collapse onto a single cache entry instead of each being scraped and
        dropped independently.
        """
        return " ".join(cls._tokens(cls._clean(company), dots_as_space=False))

    @classmethod
    def _query_forms(cls, company: str) -> list[str]:
        """Candidate `em=` values to try, broadest-matching last.

        Ordered so the most specific (and therefore most trustworthy) query runs
        first; each fallback walks one step closer to the parent brand.
        """
        cleaned = cls._clean(company)
        forms: list[str] = []

        def add(tokens: list[str]) -> None:
            if not tokens:
                return
            form = " ".join(tokens)
            if form and form not in forms:
                forms.append(form)

        base = cls._tokens(cleaned, dots_as_space=False)
        add(base)
        add(cls._tokens(cleaned, dots_as_space=True))

        # Peel generic tails one at a time: "ntt data north america" -> "ntt data",
        # "walmart global tech" -> "walmart".
        trimmed = list(base)
        while len(trimmed) > 1 and trimmed[-1] in _GENERIC_TAIL_TOKENS:
            trimmed.pop()
            # A bare one-token query matches broadly, so it is only earned when
            # every token peeled to reach it was generic decoration. That covers
            # "NVIDIA AI" -> nvidia and "KPMG US" -> kpmg, while leaving
            # "Prime Video & Amazon MGM Studios" as a multi-token query — its
            # root was never reachable by peeling decoration alone.
            if len(trimmed) > 1:
                add(trimmed)
            elif len(trimmed[0]) >= _MIN_BARE_ROOT_LEN and trimmed[0] not in _UNSAFE_ROOTS:
                add(trimmed)

        return forms[:_MAX_QUERY_FORMS]

    @staticmethod
    def _root(company_key: str) -> str:
        return company_key.split(" ", 1)[0] if company_key else ""

    def _inherits_sponsor(self, company_key: str) -> bool:
        """True if this name extends a confirmed sponsor's own cache key.

        "amazon web services" inherits because "amazon" is itself cached as a
        sponsor; "nvidia ai" inherits from "nvidia". The match is against the
        FULL key of a verified company, not merely its first word — with
        thousands of sponsors cached, a shared leading token ("allied", "jack",
        "motion") collides constantly and would wave through unrelated staffing
        firms. Requiring the parent's whole key keeps this to genuine
        brand-plus-division names.
        """
        tokens = company_key.split()
        if len(tokens) < 2:
            return False
        if len(tokens[0]) < _MIN_INHERIT_ROOT_LEN or tokens[0] in _UNSAFE_ROOTS:
            return False
        # Longest parent first: "amazon web" would be a more specific match
        # than "amazon", though either is sufficient.
        for n in range(len(tokens) - 1, 0, -1):
            if " ".join(tokens[:n]) in self._verified_keys:
                return True
        return False

    # ── scraping ──────────────────────────────────────────

    @staticmethod
    def _has_results(html: str) -> bool:
        """Return True if the h1bdata.info HTML table contains at least one data row."""
        if "no data available in table" in html.lower():
            return False
        return bool(re.search(r"<tbody[^>]*>\s*<tr", html, re.IGNORECASE))

    async def _scrape_year(
        self, session: aiohttp.ClientSession, company_key: str, year: int
    ) -> bool:
        url = (
            "https://h1bdata.info/index.php"
            f"?em={urllib.parse.quote_plus(company_key)}&job=&city=&year={year}"
        )
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=25)) as resp:
            # Read incrementally and stop as soon as the verdict is decidable —
            # a positive hit on a large employer is an 8 MB page we don't need.
            buf = bytearray()
            async for chunk in resp.content.iter_chunked(65_536):
                buf.extend(chunk)
                if re.search(rb"<tbody[^>]*>\s*<tr", buf, re.IGNORECASE):
                    return True
                if len(buf) >= _MAX_READ_BYTES:
                    break
        return self._has_results(buf.decode("utf-8", errors="replace"))

    async def _check_form(
        self, session: aiohttp.ClientSession, form: str, years: tuple[int, ...]
    ) -> bool | None:
        """Return True on any hit, False if every year was a clean miss, None on error."""
        results = await asyncio.gather(
            *[self._scrape_year(session, form, y) for y in years],
            return_exceptions=True,
        )
        if any(r is True for r in results):
            return True
        if any(isinstance(r, BaseException) for r in results):
            return None
        return False

    async def _check_company(
        self,
        sem: asyncio.Semaphore,
        session: aiohttp.ClientSession,
        company_key: str,
        company_raw: str,
    ) -> bool | None:
        """Resolve one employer through the query ladder.

        Returns True on the first form that hits, None if every form that missed
        also saw an error (inconclusive — the job is kept and nothing is cached),
        and False only when at least one form came back as a clean, error-free
        miss and no form hit.
        """
        async with sem:
            try:
                year = datetime.now(timezone.utc).year
                years = (year, year - 1)
                saw_clean_miss = False
                for form in self._query_forms(company_raw) or [company_key]:
                    result = await self._check_form(session, form, years)
                    if result is True:
                        return True
                    if result is False:
                        saw_clean_miss = True
                return False if saw_clean_miss else None
            except Exception:
                return None

    # ── batch entry point ─────────────────────────────────

    async def check_batch(self, jobs: list[RawJob]) -> None:
        """Mutate h1b_sponsor_verified on open-source jobs in-place.

        Curated sources (greenhouse-*, lever-*, ashby-*) are left as None.
        Open-source jobs get True/False from cache, brand inheritance, or an
        h1bdata.info query ladder. Error results (None) are not cached and leave
        the field as None, so the job survives to Stage 2.
        """
        open_jobs = [j for j in jobs if not j.source.startswith(_CURATED_PREFIXES)]
        if not open_jobs:
            return

        self._verified_keys = self._db.get_verified_sponsor_keys()

        # Group by normalized company key; keep one raw name per key
        by_key: dict[str, list[RawJob]] = {}
        raw_name: dict[str, str] = {}
        for job in open_jobs:
            key = self._normalize(job.company)
            if not key:
                continue
            by_key.setdefault(key, []).append(job)
            raw_name.setdefault(key, job.company)

        # Serve cache hits; collect misses
        verified: dict[str, bool | None] = {}
        misses: list[str] = []
        for key in by_key:
            hit = self._db.get_h1b_cache(key)
            if hit is True:
                verified[key] = True
            elif self._inherits_sponsor(key):
                # A decorated variant of a confirmed sponsor. Checked BEFORE a
                # cached False is honoured: "this name's parent brand files
                # H-1Bs" is stronger evidence than "a prefix query on the
                # decorated string returned nothing", which is exactly how the
                # bad negatives got written in the first place.
                verified[key] = True
                self._db.set_h1b_cache(key, raw_name[key], True)
            elif hit is False:
                verified[key] = False
            else:
                misses.append(key)

        # Scrape cache misses concurrently
        if misses:
            sem = asyncio.Semaphore(3)
            async with aiohttp.ClientSession(
                headers={"User-Agent": "Mozilla/5.0"},
            ) as session:
                results = await asyncio.gather(
                    *[
                        self._check_company(sem, session, key, raw_name[key])
                        for key in misses
                    ]
                )
            for key, result in zip(misses, results):
                verified[key] = result
                if result is not None:  # only cache definitive True/False
                    self._db.set_h1b_cache(key, raw_name[key], result)

        # Mutate jobs in-place
        for key, job_list in by_key.items():
            v = verified.get(key)
            for job in job_list:
                job.h1b_sponsor_verified = v


# Sources where "no H-1B history" reliably means "won't sponsor".
# These skew toward established companies; if they have zero LCA
# filings on record, dropping them is safe. New sources default to
# KEEP — explicitly add to this set/prefix when triaged.
_DROPPABLE_SOURCES = frozenset({"linkedin", "indeed", "google"})

# Per-tenant adapters emit `source=f"{adapter}-{tenant}"`. Workday
# tenants (e.g. "workday-broadcom") are big-company by construction.
_DROPPABLE_PREFIXES = ("workday-",)


def is_droppable_source(source: str) -> bool:
    """Return True if a source belongs to the big-company drop bucket.

    Sources outside this set are either user-curated (greenhouse/lever/ashby
    prefixes) or startup-heavy (hackernews, remoteok), where a missing
    h1bdata.info record is uninformative.
    """
    if source in _DROPPABLE_SOURCES:
        return True
    return source.startswith(_DROPPABLE_PREFIXES)


def partition_drops(jobs: list[RawJob]) -> tuple[list[RawJob], list[RawJob]]:
    """Split a list of H1B-checked jobs into (kept, dropped).

    A job is dropped iff its source is in the drop bucket AND its
    h1b_sponsor_verified is False (definitively no LCA filings).
    All other combinations — verified=True, verified=None, or any
    keep-bucket source — pass through unchanged.

    Pre-condition: callers should run H1BChecker.check_batch first so
    h1b_sponsor_verified is populated where applicable.
    """
    kept: list[RawJob] = []
    dropped: list[RawJob] = []
    for job in jobs:
        if job.h1b_sponsor_verified is False and is_droppable_source(job.source):
            dropped.append(job)
        else:
            kept.append(job)
    return kept, dropped
