"""Validate and promote Workday candidates from staging to active scraping.

The promotion gate is DOMAIN RELEVANCE: a board must currently advertise at
least MIN_DOMAIN_HITS titles that pass Stage 1's title-domain filter. This
self-curates the noisy discovery queue — banks, hospitals, universities and
other off-domain tenants get rejected instead of bloating the active scrape.

The gate used to switch to H-1B history whenever SPONSORSHIP_FILTER_ENABLED was
on. That was wrong in both directions: it promoted tenants with zero engineering
roles on the strength of their filing history, and rejected on-domain employers
that had none. It was also redundant — workday-* is a droppable source, so every
posting is sponsor-checked at scrape time by screening/h1b_checker.py regardless
of how the tenant got promoted.

A dead board (404/422/parse error) is always rejected.

Disposition per candidate:
  * **PROMOTE** -> append to target_companies.yaml workday section
  * **REJECT**  -> append to workday_rejected.yaml (reason: dead_board /
                   no_domain_roles / auto_validation_failed). Restorable by
                   removing the entry and re-running.
  * **RETRY**   -> board probe errored (transient); increment promotion_attempts;
                   auto-reject as `validation_max_attempts` once MAX_ATTEMPTS hit.

Idempotent: re-running picks up where the previous run left off.
Run: `python scripts/promote_workday_candidates.py`
Add `--dry-run` to print actions without writing files.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import logging
import pathlib
import random
import re
import sys

import aiohttp

# Allow running as a script from anywhere.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from db.database import Database  # noqa: E402
from screening.h1b_checker import H1BChecker  # noqa: E402
from config import TITLE_DOMAIN_KEYWORDS  # noqa: E402

CANDIDATES_YAML = _REPO_ROOT / "workday_candidates.yaml"
TARGET_YAML = _REPO_ROOT / "target_companies.yaml"
REJECTED_YAML = _REPO_ROOT / "workday_rejected.yaml"
DB_FILE = _REPO_ROOT / "jobs.db"

# After this many failed validation attempts, give up and reject.
MAX_ATTEMPTS = 5

# Search terms used for the active-board probe. "engineer" surfaces the bulk of
# IC roles; "cloud" catches infrastructure titles that never say "engineer"
# (Cloud Administrator, Cloud Operations). A live tech tenant returns domain
# titles for these; a hospital or bank returns facilities/clinical/teller roles
# that fail the domain filter.
#
# "security" was the second term until 2026-09-13. It stopped being a useful
# relevance signal once security words left TITLE_DOMAIN_KEYWORDS — the probe
# was spending half its budget fetching titles that can no longer score.
PROBE_SEARCH_TERMS = ("engineer", "cloud")
PROBE_LIMIT = 20  # Workday's jobs API hard-caps limit at 20; >20 returns HTTP 400
PROBE_TIMEOUT = 15.0
PROBE_CONCURRENCY = 4
# Transient failures (HTTP 429/5xx, network/timeout) are RETRIED with
# exponential backoff before giving up — without this, Workday rate-limiting a
# large batch turns every board into a false `None` (retry), which would burn
# promotion_attempts and eventually auto-reject good companies. Definitive
# results (200/404/422) are never retried.
PROBE_RETRIES = 3
PROBE_BACKOFF = 1.5  # base seconds; sleep = PROBE_BACKOFF * 2**attempt + jitter

# Domain-relevance promote bar.
# The probe samples up to ~40 titles (PROBE_LIMIT per term x PROBE_SEARCH_TERMS)
# from the PROBE_SEARCH_TERMS searches; domain_hits counts how many pass Stage 1's
# title-domain filter. A high count means MUCH of a board's engineering/cloud
# output is genuinely infrastructure work — i.e. a tech-centric employer — rather
# than a bank/hospital with a couple of IT roles among hundreds of unrelated ones. Tune this for the coverage-vs-runtime tradeoff:
# higher = fewer, more tech-focused tenants added to the active scrape.
# Boards with SOME but sub-bar relevance are HELD (kept for re-eval), not rejected.
#
# Lowered 10 -> 6 on 2026-09-13. At 10, only 27 of 955 queued tenants promoted
# while 533 sat held; the probe samples ~40 titles, so 6 still means roughly
# one in seven of a board's engineering/cloud results is an infrastructure role.
# The old calibration note (">=6 ~135 tenants" of 426) predates the removal of
# security terms from TITLE_DOMAIN_KEYWORDS and no longer holds.
MIN_DOMAIN_HITS = 6

# Same word-boundary matching as screening.stage1, so "a board gets promoted
# iff it has titles that would survive Stage 1".
_DOMAIN_RES = [re.compile(r"\b" + re.escape(k) + r"\b", re.IGNORECASE) for k in TITLE_DOMAIN_KEYWORDS]


def _is_domain_title(title: str) -> bool:
    return any(rx.search(title) for rx in _DOMAIN_RES)


# Reuse H1BChecker's per-company semaphore default (3) to be polite.
H1B_CONCURRENCY = 3

logger = logging.getLogger("promote_workday_candidates")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


# ── Active-board probe ────────────────────────────────────────────────────
async def _probe_workday_board(
    session: aiohttp.ClientSession,
    tenant: str,
    wd_server: str,
    site: str,
) -> tuple[bool | None, int]:
    """Hit the Workday jobs API. Return (alive, domain_hits) where:

      alive: True (HTTP 200 + parseable jobPostings), False (404/422/parse
             error -> definitively dead), None (network/transient error).
      domain_hits: count of DISTINCT returned titles that pass Stage 1's
             title-domain filter. 0 unless alive.

    Runs one search per PROBE_SEARCH_TERMS and unions the titles seen.
    """
    url = (
        f"https://{tenant}.{wd_server}.myworkdayjobs.com"
        f"/wday/cxs/{tenant}/{site}/jobs"
    )
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
    }
    alive: bool | None = None
    titles: set[str] = set()

    for term in PROBE_SEARCH_TERMS:
        body = {"searchText": term, "limit": PROBE_LIMIT, "offset": 0, "appliedFacets": {}}
        for attempt in range(PROBE_RETRIES):
            try:
                async with session.post(
                    url, json=body, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=PROBE_TIMEOUT),
                ) as resp:
                    if resp.status == 200:
                        try:
                            data = await resp.json(content_type=None)
                        except Exception:
                            if alive is None:
                                alive = False  # 200 but unparseable -> dead
                            break
                        if isinstance(data, dict) and "jobPostings" in data:
                            alive = True  # a positive result wins over earlier negatives
                            for p in data["jobPostings"]:
                                t = (p.get("title") or "").strip()
                                if t:
                                    titles.add(t)
                        elif alive is None:
                            alive = False
                        break  # definitive 200 result — done with this term
                    if resp.status in (404, 422):
                        if alive is None:
                            alive = False  # definitively dead
                        break
                    # 429 / 5xx / other -> fall through to backoff + retry
            except Exception:
                pass  # network/timeout -> fall through to backoff + retry
            # Transient: back off and retry unless this was the last attempt.
            if attempt < PROBE_RETRIES - 1:
                await asyncio.sleep(PROBE_BACKOFF * (2 ** attempt) + random.uniform(0, 0.5))

    hits = sum(1 for t in titles if _is_domain_title(t))
    return alive, hits


async def _probe_all(candidates: list[dict]) -> dict[str, tuple[bool | None, int]]:
    sem = asyncio.Semaphore(PROBE_CONCURRENCY)

    async def _one(session: aiohttp.ClientSession, c: dict) -> tuple[str, tuple[bool | None, int]]:
        async with sem:
            result = await _probe_workday_board(
                session, c["tenant"], c["wd_server"], c["site"]
            )
            return c["tenant"], result

    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*[_one(session, c) for c in candidates])
    return dict(results)


# ── H-1B check (reuses H1BChecker internals) ──────────────────────────────
async def _check_h1b_all(candidates: list[dict], db: Database) -> dict[str, bool | None]:
    """Return tenant -> True/False/None from h1bdata.info."""
    if not candidates:
        return {}
    checker = H1BChecker(db)
    sem = asyncio.Semaphore(H1B_CONCURRENCY)

    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        async def _one(c: dict) -> tuple[str, bool | None]:
            key = checker._normalize(c["name"])
            if not key:
                return c["tenant"], None
            # Cache hit short-circuits the HTTP call
            cached = db.get_h1b_cache(key)
            if cached is not None:
                return c["tenant"], cached
            result = await checker._check_company(sem, session, key, c["name"])
            if result is not None:
                db.set_h1b_cache(key, c["name"], result)
            return c["tenant"], result

        results = await asyncio.gather(*[_one(c) for c in candidates])
    return dict(results)


# ── Disposition ───────────────────────────────────────────────────────────
def _decide(
    h1b: bool | None, board_alive: bool | None, domain_hits: int
) -> tuple[str, str]:
    """Map probe results -> (decision, reason). decision is promote|reject|retry.

    Gates on domain relevance only — see module docstring.
    """
    # A dead board can never be scraped, regardless of policy.
    if board_alive is False:
        return "reject", "dead_board"
    # Board probe errored (network/transient) — try again on a later run.
    if board_alive is None:
        return "retry", ""

    # board_alive is True from here.
    #
    # Domain relevance is the gate in BOTH sponsorship modes as of 2026-09-13.
    # It used to be H-1B history whenever SPONSORSHIP_FILTER_ENABLED was on,
    # which got the decision backwards in both directions: it promoted tenants
    # with zero engineering roles (an accounting firm, a county government) on
    # the strength of their filing history, and rejected genuinely on-domain
    # employers like Valeo (8 domain hits) for having none.
    #
    # Gating on H-1B here was also redundant. Workday sources sit in the
    # runtime drop bucket (see screening/h1b_checker.is_droppable_source), so
    # every workday-* posting is sponsor-checked on the way through the
    # pipeline anyway — with the fixed matcher, a better check than this one.
    # Promotion only has to answer "is this board worth scraping at all".
    if domain_hits >= MIN_DOMAIN_HITS:
        return "promote", ""
    if domain_hits == 0:
        # Truly off-domain (banks/hospitals/etc.) — reject so discovery
        # stops re-surfacing it.
        return "reject", "no_domain_roles"
    # Some relevance but below the promote bar. Don't promote (would bloat
    # the scrape) and don't permanently reject (it has real domain roles) —
    # HOLD it in the queue for re-evaluation as its postings change.
    return "hold", ""


# ── YAML I/O ──────────────────────────────────────────────────────────────
def _load_yaml(path: pathlib.Path) -> dict:
    from ruamel.yaml import YAML
    if not path.exists():
        return {}
    yaml = YAML()
    # Explicit UTF-8: these files carry box-drawing section headers and
    # non-ASCII company names, and Windows would otherwise decode as cp1252.
    with open(path, encoding="utf-8") as f:
        return yaml.load(f) or {}


def _dump_yaml(path: pathlib.Path, data: dict, header: str = "") -> None:
    from ruamel.yaml import YAML
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        if header:
            f.write(header)
        yaml.dump(data, f)


_REJECTED_HEADER = (
    "# Workday tenants rejected from active scraping.\n"
    "# Auto-discovery (sources/workday_discovery.py) skips any tenant in this file.\n"
    "# Reason codes:\n"
    "#   industry_mismatch    — wrong industry (healthcare, govt, edu, etc.)\n"
    "#   low_h1b_sponsorship  — sponsors rarely / not for cloud-devops roles\n"
    "#   defense_clearance    — most roles require US-citizen clearance\n"
    "#   dead_board           — Workday board returns 404/422/parse errors\n"
    "#   no_domain_roles      — board is live but advertises no cloud/devops/security roles\n"
    "#   auto_validation_failed     — failed h1b + active-board checks\n"
    "#   validation_max_attempts    — hit MAX_ATTEMPTS without resolution\n"
    "#\n"
    "# To restore a tenant: remove its entry here and re-run promotion.\n"
)


# ── Main flow ─────────────────────────────────────────────────────────────
async def _run(dry_run: bool) -> int:
    cdata = _load_yaml(CANDIDATES_YAML)
    candidates: list[dict] = list(cdata.get("candidates") or [])
    if not candidates:
        logger.info("No candidates to validate. Nothing to do.")
        return 0

    logger.info(f"Validating {len(candidates)} candidate(s)...")

    db = Database(str(DB_FILE))
    db.initialize()

    try:
        # Promotion gates on domain relevance only. Sponsorship is enforced at
        # runtime instead — workday-* is a droppable source, so every posting
        # gets sponsor-checked as it flows through the pipeline. Scraping
        # h1bdata.info for ~1k tenants here would just duplicate that slowly.
        logger.info(
            f"Promoting boards with >= {MIN_DOMAIN_HITS} infrastructure roles; "
            "sponsorship is enforced at scrape time, not here."
        )
        board_results = await _probe_all(candidates)
        h1b_results = {}
    finally:
        db.close()

    today = _dt.date.today().isoformat()
    promotions: list[dict] = []
    rejections: list[dict] = []
    retained: list[dict] = []
    held = 0

    for c in candidates:
        tenant = c["tenant"]
        h1b = h1b_results.get(tenant)
        alive, domain_hits = board_results.get(tenant, (None, 0))
        decision, reason = _decide(h1b, alive, domain_hits)

        if decision == "promote":
            promotions.append({
                "tenant": tenant,
                "wd_server": c["wd_server"],
                "site": c["site"],
                "name": c["name"],
            })
            logger.info(
                f"  PROMOTE  {tenant:30} (board=alive, domain_hits={domain_hits}, h1b={h1b})"
            )
        elif decision == "hold":
            # Below the promote bar but has real domain roles — keep unchanged
            # (no attempt increment, no rejection) for re-evaluation next run.
            retained.append(c)
            held += 1
        elif decision == "reject":
            rejections.append({
                "tenant": tenant,
                "name": c["name"],
                "wd_server": c["wd_server"],
                "site": c["site"],
                "reason": reason,
                "h1b_result": str(h1b),
                "board_alive": str(alive),
                "domain_hits": domain_hits,
                "rejected_on": today,
            })
            logger.info(
                f"  REJECT   {tenant:30} "
                f"({reason}; domain_hits={domain_hits}, h1b={h1b}, board={alive})"
            )
        else:
            attempts = int(c.get("promotion_attempts", 0)) + 1
            if attempts >= MAX_ATTEMPTS:
                rejections.append({
                    "tenant": tenant,
                    "name": c["name"],
                    "wd_server": c["wd_server"],
                    "site": c["site"],
                    "reason": "validation_max_attempts",
                    "h1b_result": str(h1b),
                    "board_alive": str(alive),
                    "domain_hits": domain_hits,
                    "attempts": attempts,
                    "rejected_on": today,
                })
                logger.info(
                    f"  REJECT   {tenant:30} "
                    f"(max attempts {attempts} reached, domain_hits={domain_hits}, board={alive})"
                )
            else:
                c["promotion_attempts"] = attempts
                c["last_attempt"] = today
                retained.append(c)
                logger.info(
                    f"  RETRY    {tenant:30} "
                    f"(attempt {attempts}/{MAX_ATTEMPTS}, domain_hits={domain_hits}, board={alive})"
                )

    logger.info(
        f"Result: {len(promotions)} promoted, {len(rejections)} rejected, "
        f"{held} held (sub-bar relevance), {len(retained) - held} retained for retry"
    )

    if dry_run:
        logger.info("--dry-run set; not writing any files.")
        return 0

    # ── Write target_companies.yaml (append promotions) ──
    if promotions:
        target = _load_yaml(TARGET_YAML)
        target.setdefault("workday", [])
        active_tenants = {c["tenant"] for c in target["workday"] if "tenant" in c}
        for p in promotions:
            if p["tenant"] not in active_tenants:
                target["workday"].append(p)
        _dump_yaml(TARGET_YAML, target)

    # ── Write workday_rejected.yaml (merge rejections) ──
    if rejections:
        rejected_data = _load_yaml(REJECTED_YAML)
        existing = list(rejected_data.get("rejected") or [])
        by_tenant = {r["tenant"]: r for r in existing}
        for r in rejections:
            by_tenant[r["tenant"]] = r
        merged = sorted(by_tenant.values(), key=lambda r: r["tenant"])
        _dump_yaml(REJECTED_YAML, {"rejected": merged}, header=_REJECTED_HEADER)

    # ── Rewrite workday_candidates.yaml (only the retained set) ──
    cdata["candidates"] = retained
    _dump_yaml(CANDIDATES_YAML, cdata)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print actions without writing any files.",
    )
    args = parser.parse_args()

    _setup_logging()
    return asyncio.run(_run(args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
