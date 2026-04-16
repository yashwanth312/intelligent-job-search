"""
============================================================
  INTELLIGENT JOB SEARCH — Main Pipeline
============================================================
  1. Validate config + credentials (fail-fast)
  2. Clear Daily + Audit tabs
  3. Parallel scrape all sources
  4. Dedup (cross-source + against SQLite)
  5. Stage 1: Regex fast filter
  6. Bulk save to SQLite
  7. Stage 2: Claude CLI precision screen
  8. Write to Daily + Audit tabs
  9. Print run summary
============================================================
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

import yaml

from config import (
    TARGET_TITLES, LOCATIONS, DB_FILE,
    SCREENING_CONFIDENCE_THRESHOLD,
)
from db.database import Database
from models.job import ScreenedJob, ScreeningVerdict
from screening.stage1 import Stage1Filter
from screening.stage2 import Stage2Screen
from sheets.client import SheetsClient
from sheets import daily as daily_ops, audit as audit_ops
from sources.orchestrator import ScraperOrchestrator
from sources.greenhouse import GreenhouseAdapter
from sources.lever import LeverAdapter
from sources.linkedin_indeed import LinkedInIndeedAdapter
from sources.hackernews import HackerNewsAdapter
from sources.remoteok import RemoteOKAdapter

# Fix Windows console encoding
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            f"logs/run_{date.today().isoformat()}.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)


def load_target_companies() -> dict:
    path = Path("target_companies.yaml")
    if not path.exists():
        return {"greenhouse": [], "lever": [], "ashby": []}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def build_adapters(companies: dict) -> list:
    adapters = []

    gh = companies.get("greenhouse", [])
    if gh:
        adapters.append(GreenhouseAdapter(companies=gh))

    lv = companies.get("lever", [])
    if lv:
        adapters.append(LeverAdapter(companies=lv))

    adapters.append(LinkedInIndeedAdapter())
    adapters.append(HackerNewsAdapter())
    adapters.append(RemoteOKAdapter())

    return adapters


def print_summary(
    total_scraped: int, dupes: int, stage1_passed: int, stage1_rejected: int,
    stage2_results: list[ScreenedJob], errors: list[str],
) -> None:
    apply_count = sum(1 for j in stage2_results if j.verdict == ScreeningVerdict.APPLY)
    maybe_count = sum(1 for j in stage2_results if j.verdict == ScreeningVerdict.MAYBE)
    skip_count = sum(1 for j in stage2_results if j.verdict == ScreeningVerdict.SKIP)

    print("\n" + "=" * 55)
    print("  INTELLIGENT JOB SEARCH — Run Summary")
    print(f"  {date.today().isoformat()}")
    print("=" * 55)
    print(f"\n  Total scraped:      {total_scraped}")
    print(f"  Duplicates removed: {dupes}")
    print(f"\n  STAGE 1 FILTER")
    print(f"  Passed:    {stage1_passed}")
    print(f"  Rejected:  {stage1_rejected}")
    print(f"\n  STAGE 2 CLAUDE SCREEN")
    print(f"  APPLY:  {apply_count}")
    print(f"  MAYBE:  {maybe_count}")
    print(f"  SKIP:   {skip_count}")
    print(f"\n  -> {apply_count + maybe_count} jobs written to Daily tab")
    if errors:
        print(f"\n  Warning: {len(errors)} source errors (check logs)")
    print("=" * 55 + "\n")


async def run_pipeline():
    # -- Fail-fast validation --
    Path("logs").mkdir(exist_ok=True)

    if not Path("profile.yaml").exists():
        logger.error("profile.yaml not found. Run update_profile.py first.")
        sys.exit(1)

    # -- Initialize --
    db = Database(DB_FILE)
    db.initialize()

    sheets = SheetsClient()
    daily_ws = sheets.get_daily_sheet()
    audit_ws = sheets.get_audit_sheet()

    # -- Save yesterday's data to SQLite, then clear --
    daily_ops.clear_and_write_headers(daily_ws)
    audit_ops.clear_and_write_headers(audit_ws)

    # -- Scrape --
    companies = load_target_companies()
    adapters = build_adapters(companies)
    orchestrator = ScraperOrchestrator(adapters)

    known_fps = db.get_known_fingerprints(set())
    scrape_result = await orchestrator.scrape_all(
        TARGET_TITLES, LOCATIONS, known_fingerprints=known_fps,
    )

    unique_jobs = scrape_result.jobs

    # -- Stage 1: Regex filter --
    stage1 = Stage1Filter()
    passed_jobs, rejected = stage1.filter_batch(unique_jobs)

    # Save all jobs to SQLite
    db.save_jobs(unique_jobs)

    # Save audit entries for rejected jobs
    today_str = date.today().isoformat()
    audit_entries = [
        {
            "job_fingerprint": r.job.fingerprint,
            "company": r.job.company,
            "title": r.job.title,
            "source": r.job.source,
            "stage": r.stage,
            "verdict": "REJECT",
            "reason": r.reason,
            "confidence": None,
            "run_date": today_str,
        }
        for r in rejected
    ]
    if audit_entries:
        db.save_audit_entries_bulk(audit_entries)

    # -- Stage 2: Claude CLI screen --
    stage2 = Stage2Screen(profile_path="profile.yaml")
    screened_jobs = stage2.screen_batch(passed_jobs)

    # Save stage 2 audit entries
    stage2_audit = [
        {
            "job_fingerprint": j.fingerprint,
            "company": j.company,
            "title": j.title,
            "source": j.source,
            "stage": "stage2_claude",
            "verdict": j.verdict.value,
            "reason": j.reasoning,
            "confidence": j.confidence,
            "run_date": today_str,
        }
        for j in screened_jobs
    ]
    if stage2_audit:
        db.save_audit_entries_bulk(stage2_audit)

    # -- Write to Sheets --
    daily_jobs = [
        j for j in screened_jobs
        if j.verdict in (ScreeningVerdict.APPLY, ScreeningVerdict.MAYBE)
    ]
    daily_ops.write_screened_jobs(daily_ws, daily_jobs)

    # Audit tab: Stage 1 rejections + Stage 2 SKIP jobs
    audit_ops.write_rejections(audit_ws, rejected)
    stage2_skips = [
        type("FilterResult", (), {
            "job": j, "stage": "stage2_claude",
            "reason": j.reasoning, "passed": False,
        })()
        for j in screened_jobs if j.verdict == ScreeningVerdict.SKIP
    ]
    if stage2_skips:
        audit_ops.write_rejections(audit_ws, stage2_skips)

    # -- Summary --
    print_summary(
        total_scraped=len(unique_jobs),
        dupes=0,
        stage1_passed=len(passed_jobs),
        stage1_rejected=len(rejected),
        stage2_results=screened_jobs,
        errors=scrape_result.errors,
    )

    db.close()


def main():
    asyncio.run(run_pipeline())


if __name__ == "__main__":
    main()
