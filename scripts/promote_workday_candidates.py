"""Validate and promote Workday candidates from staging to active scraping.

For each candidate in workday_candidates.yaml:
  1. **H-1B sponsor check** via h1bdata.info (using H1BChecker infrastructure).
     Definitive False = company has zero LCA filings in last 2 years.
  2. **Active board check** — single Workday API call with a known tech title.
     Validates tenant/wd_server/site fields are correct AND board is publicly
     accessible.

Disposition logic per candidate:
  * **PROMOTE** (both checks pass)         -> append to target_companies.yaml
  * **REJECT** (both checks definitively fail) -> append to workday_rejected.yaml
                                                  with reason `auto_validation_failed`
  * **RETRY** (any check errored)          -> increment promotion_attempts; if it
                                              hits MAX_ATTEMPTS, auto-reject as
                                              `validation_max_attempts`

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
import sys

import aiohttp

# Allow running as a script from anywhere.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from db.database import Database  # noqa: E402
from screening.h1b_checker import H1BChecker  # noqa: E402

CANDIDATES_YAML = _REPO_ROOT / "workday_candidates.yaml"
TARGET_YAML = _REPO_ROOT / "target_companies.yaml"
REJECTED_YAML = _REPO_ROOT / "workday_rejected.yaml"
DB_FILE = _REPO_ROOT / "jobs.db"

# After this many failed validation attempts, give up and reject.
MAX_ATTEMPTS = 5

# Single title used for the active-board check. Generic enough that any
# tech-adjacent Workday tenant should return at least one result if the
# board is alive. We don't care about result count — only that the API
# responded with HTTP 200 + parseable JSON.
PROBE_TITLE = "Engineer"
PROBE_TIMEOUT = 15.0
PROBE_CONCURRENCY = 4

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
) -> bool | None:
    """Hit the Workday jobs API once. Return True if alive (HTTP 200 + JSON),
    False if dead (4xx / parse error), None if request errored (network).
    """
    url = (
        f"https://{tenant}.{wd_server}.myworkdayjobs.com"
        f"/wday/cxs/{tenant}/{site}/jobs"
    )
    body = {"searchText": PROBE_TITLE, "limit": 1, "offset": 0, "appliedFacets": {}}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
    }
    try:
        async with session.post(
            url, json=body, headers=headers,
            timeout=aiohttp.ClientTimeout(total=PROBE_TIMEOUT),
        ) as resp:
            if resp.status == 200:
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    return False  # 200 but unparseable -> definitively dead
                return isinstance(data, dict) and "jobPostings" in data
            if resp.status in (404, 422):
                return False  # definitively dead
            return None  # other status -> ambiguous, treat as transient
    except Exception:
        return None


async def _probe_all(candidates: list[dict]) -> dict[str, bool | None]:
    sem = asyncio.Semaphore(PROBE_CONCURRENCY)

    async def _one(session: aiohttp.ClientSession, c: dict) -> tuple[str, bool | None]:
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
    h1b: bool | None, board_alive: bool | None
) -> str:
    """Map (h1b_result, board_result) -> 'promote' | 'reject' | 'retry'."""
    # PROMOTE: both definitively pass
    if h1b is True and board_alive is True:
        return "promote"
    # REJECT: both definitively fail
    if h1b is False and board_alive is False:
        return "reject"
    # REJECT: dead board even if h1b is good — can't scrape what doesn't respond
    if board_alive is False:
        return "reject"
    # REJECT: company has no h1b history AND board responded — clear signal
    if h1b is False and board_alive is True:
        return "reject"
    # Anything with a None result -> retry
    return "retry"


# ── YAML I/O ──────────────────────────────────────────────────────────────
def _load_yaml(path: pathlib.Path) -> dict:
    from ruamel.yaml import YAML
    if not path.exists():
        return {}
    yaml = YAML()
    with open(path) as f:
        return yaml.load(f) or {}


def _dump_yaml(path: pathlib.Path, data: dict, header: str = "") -> None:
    from ruamel.yaml import YAML
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
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
        # Run both check batches concurrently — they hit different hosts.
        h1b_task = asyncio.create_task(_check_h1b_all(candidates, db))
        board_task = asyncio.create_task(_probe_all(candidates))
        h1b_results, board_results = await asyncio.gather(h1b_task, board_task)
    finally:
        db.close()

    today = _dt.date.today().isoformat()
    promotions: list[dict] = []
    rejections: list[dict] = []
    retained: list[dict] = []

    for c in candidates:
        tenant = c["tenant"]
        h1b = h1b_results.get(tenant)
        alive = board_results.get(tenant)
        decision = _decide(h1b, alive)

        if decision == "promote":
            promotions.append({
                "tenant": tenant,
                "wd_server": c["wd_server"],
                "site": c["site"],
                "name": c["name"],
            })
            logger.info(f"  PROMOTE  {tenant:30} (h1b=True, board=alive)")
        elif decision == "reject":
            rejections.append({
                "tenant": tenant,
                "name": c["name"],
                "wd_server": c["wd_server"],
                "site": c["site"],
                "reason": "auto_validation_failed",
                "h1b_result": str(h1b),
                "board_alive": str(alive),
                "rejected_on": today,
            })
            logger.info(f"  REJECT   {tenant:30} (h1b={h1b}, board={alive})")
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
                    "attempts": attempts,
                    "rejected_on": today,
                })
                logger.info(
                    f"  REJECT   {tenant:30} "
                    f"(max attempts {attempts} reached, last h1b={h1b}, board={alive})"
                )
            else:
                c["promotion_attempts"] = attempts
                c["last_attempt"] = today
                retained.append(c)
                logger.info(
                    f"  RETRY    {tenant:30} "
                    f"(attempt {attempts}/{MAX_ATTEMPTS}, h1b={h1b}, board={alive})"
                )

    logger.info(
        f"Result: {len(promotions)} promoted, {len(rejections)} rejected, "
        f"{len(retained)} retained for retry"
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
