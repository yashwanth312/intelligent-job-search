"""H1B sponsor check against DOL LCA filings — Phase 5 of the pipeline.

Where the verdict comes from
----------------------------
screening/lca_index.LcaIndex: every employer (legal name and trade name) on a
certified H-1B Labor Condition Application in the DOL disclosure files, built
offline by scripts/build_lca_index.py. Until 2026-10-09 this module scraped
h1bdata.info, which indexes the same filings; that site started answering
"0 records found" for Microsoft, IBM and JPMorganChase, and a throttled page
was indistinguishable from a real miss, so big sponsors were cached as
non-sponsors and every one of their postings dropped.

Why the name handling below exists
----------------------------------
Job boards publish decorated company strings: "Amazon Web Services (AWS)",
"NVIDIA AI", "Walmart Global Tech", "Hakkoda, an IBM Company". None of those
is the legal filer name, so a single literal lookup misses and the employer is
recorded as a non-sponsor. "Amazon Web Services (AWS)" alone accounted for
3,139 dropped postings before the cleaning and query ladder were added. The
lookup is a prefix match over compact keys (letters and digits only), so
punctuation and spacing differences ("AT&T", "Amazon.com", "JPMorganChase")
no longer matter.

The filter is deliberately asymmetric. A false negative silently removes an
employer from the pipeline; a false positive costs one Stage 2 screen, which
then rejects it anyway. Every ambiguity resolves toward KEEP, and with no
index on disk nothing is dropped at all.
"""
from __future__ import annotations

import logging
import re

from db.database import Database
from models.job import RawJob
from screening.lca_index import LcaIndex, compact

logger = logging.getLogger(__name__)

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

# Direct-ATS boards (greenhouse-/lever-/ashby-) used to skip the sponsor check:
# sampling showed ~85% of board companies were verified sponsors, so the
# exemption was kept on measurement. Dropped 2026-10-03 at the user's call —
# the other ~15% were reaching the Daily sheet as applications that could not
# convert (10 known non-sponsors on 2026-10-02 alone). Boards are now checked
# and dropped exactly like LinkedIn/Workday; short or generic names that can't
# prefix-match a filer are the known false-negative risk, mitigated by the
# 7-day negative TTL.

# Bound on how many query forms are tried per company before concluding "no
# filings". The broadest forms come last and are the likeliest false hits.
_MAX_QUERY_FORMS = 4


_LOAD_DEFAULT = object()


class H1BChecker:
    def __init__(self, db: Database, index: "LcaIndex | None | object" = _LOAD_DEFAULT) -> None:
        """`index` defaults to data/h1b_filers.txt. Pass None to run with no
        index: then only cached and inherited sponsors are verified and every
        other company is left unknown (kept)."""
        self._db = db
        self._index = LcaIndex.load() if index is _LOAD_DEFAULT else index
        self._verified_keys: set[str] = set()

    @property
    def index(self) -> LcaIndex | None:
        return self._index

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

        `dots_as_space` picks between the two ways a filer name treats dots:
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
        collapse onto a single cache entry instead of each being looked up and
        dropped independently.
        """
        return " ".join(cls._tokens(cls._clean(company), dots_as_space=False))

    @classmethod
    def filer_key(cls, legal_name: str) -> str:
        """Index key for a name as filed with DOL: normalized, then compacted.

        Shared by scripts/build_lca_index.py and every lookup, so both sides
        of a match are normalized the same way.
        """
        return compact(cls._normalize(legal_name))

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

    # ── lookup ────────────────────────────────────────────

    def _lookup(self, company_key: str, company_raw: str) -> bool | None:
        """Resolve one employer through the query ladder against the index.

        True if any form matches a filer, False if none does, None when there
        is no index to ask (unknown, so the job is kept).
        """
        if self._index is None:
            return None
        forms = self._query_forms(company_raw) or [company_key]
        return any(self._index.matches(compact(form)) for form in forms)

    # ── batch entry point ─────────────────────────────────

    async def check_batch(self, jobs: list[RawJob]) -> None:
        """Set h1b_sponsor_verified on every job in-place.

        A cached True or an inherited parent brand verifies a company; anything
        else is decided by the index. Cached negatives are never trusted on
        their own: the h1bdata-era ones were wrong for big sponsors, and a
        lookup is cheap enough to redo. Unknown (None) is never cached.

        Still a coroutine so main._h1b_check_with_timeout can bound it, though
        nothing in it waits on the network any more.
        """
        self._verified_keys = self._db.get_verified_sponsor_keys()
        if self._index is None:
            logger.warning(
                "H-1B index missing (data/h1b_filers.txt) — no company can be "
                "ruled out, so the no-sponsor drop is effectively off. Build it "
                "with `python scripts/build_lca_index.py`."
            )

        # Group by normalized company key; keep one raw name per key
        by_key: dict[str, list[RawJob]] = {}
        raw_name: dict[str, str] = {}
        for job in jobs:
            key = self._normalize(job.company)
            if not key:
                continue
            by_key.setdefault(key, []).append(job)
            raw_name.setdefault(key, job.company)

        for key, key_jobs in by_key.items():
            if self._db.get_h1b_cache(key) is True:
                verdict: bool | None = True
            elif self._inherits_sponsor(key):
                # A decorated variant of a confirmed sponsor. Checked BEFORE the
                # index: "this name's parent brand files H-1Bs" is stronger
                # evidence than a prefix lookup on the decorated string missing.
                verdict = True
                self._db.set_h1b_cache(key, raw_name[key], True)
            else:
                verdict = self._lookup(key, raw_name[key])
                if verdict is not None:  # only cache definitive True/False
                    self._db.set_h1b_cache(key, raw_name[key], verdict)
            for job in key_jobs:
                job.h1b_sponsor_verified = verdict


# Sources where "no H-1B history" reliably means "won't sponsor".
# These skew toward established companies; if they have zero LCA
# filings on record, dropping them is safe. New sources default to
# KEEP — explicitly add to this set/prefix when triaged.
_DROPPABLE_SOURCES = frozenset({"linkedin", "indeed", "google"})

# Per-tenant adapters emit `source=f"{adapter}-{tenant}"`. Workday
# tenants (e.g. "workday-broadcom") are big-company by construction; board
# ATS sources joined the drop bucket on 2026-10-03 (see the note above
# H1BChecker).
_DROPPABLE_PREFIXES = ("workday-", "greenhouse-", "lever-", "ashby-")


def is_droppable_source(source: str) -> bool:
    """Return True if a source belongs to the drop bucket.

    Sources outside it are startup-heavy (hackernews, remoteok), where a
    missing LCA record is uninformative.
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
