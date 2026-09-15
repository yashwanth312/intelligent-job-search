"""
============================================================
  INTELLIGENT JOB SEARCH — Main Pipeline
============================================================
  1. Init (creds + profile + DB)
  2. Clear Daily + Audit tabs
  3. Parallel scrape all sources
  4. Freshness filter (<= HOURS_OLD)
  5. H1B Sponsor Check + source-aware drop
  6. Stage 1 regex filter
  7. Persist to SQLite
  8. Stage 2 Claude CLI precision screen
  9. Write to Daily + Audit
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
    HOURS_OLD, STALE_JOB_DAYS,
    SPONSORSHIP_FILTER_ENABLED,
    validate_required_config,
)
from db.database import Database
from models.job import ScreenedJob, ScreeningVerdict
from output.ui import PipelineUI, install_rich_logging
from screening.stage1 import FilterResult, Stage1Filter
from screening.stage2 import Stage2Screen
from screening.h1b_checker import H1BChecker, partition_drops
from sheets.client import SheetsClient
from sheets import daily as daily_ops, audit as audit_ops
from sheets.formatting import format_all_sheets
from sources.orchestrator import ScraperOrchestrator, filter_fresh_jobs
from sources.greenhouse import GreenhouseAdapter
from sources.lever import LeverAdapter
from sources.ashby import AshbyAdapter
from sources.linkedin_indeed import LinkedInIndeedAdapter
from sources.hackernews import HackerNewsAdapter
from sources.remoteok import RemoteOKAdapter
from sources.workday import WorkdayAdapter, fetch_descriptions as fetch_workday_descriptions
from sources.workday_discovery import save_candidates

# Fix Windows console encoding
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TOTAL_PHASES = 9

# NOTE: logging + the rich console are deliberately NOT initialized at import
# time. This module is imported by the test suite for its helper functions
# (_dedup_daily_jobs, build_adapters, etc.); a module-level install_rich_logging()
# call used to attach a FileHandler to logs/run_<today>.log on every such
# import, so running pytest interleaved real pipeline runs with test-fixture
# log noise ("TestCo", "Source is down", ...) into the same file. See
# run_pipeline() below, which sets this up only when the pipeline actually runs.
logger = logging.getLogger(__name__)


def load_target_companies() -> dict:
    path = Path("target_companies.yaml")
    if not path.exists():
        return {"greenhouse": [], "lever": [], "ashby": []}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def build_adapters(
    companies: dict,
) -> tuple[list, list[tuple[str, str]], LinkedInIndeedAdapter]:
    """Returns (adapters, display_sources, li_adapter).

    li_adapter is returned separately so run_pipeline can read
    discovered_workday_companies from it after scraping completes.
    """
    adapters = []
    display: list[tuple[str, str]] = []

    gh = companies.get("greenhouse", [])
    if gh:
        adapters.append(GreenhouseAdapter(companies=gh))
        display.append(("greenhouse", f"Greenhouse ({len(gh)} co)"))

    lv = companies.get("lever", [])
    if lv:
        adapters.append(LeverAdapter(companies=lv))
        display.append(("lever", f"Lever ({len(lv)} co)"))

    ab = companies.get("ashby", [])
    if ab:
        adapters.append(AshbyAdapter(companies=ab))
        display.append(("ashby", f"Ashby ({len(ab)} co)"))

    li_adapter = LinkedInIndeedAdapter()
    adapters.append(li_adapter)
    display.append(("linkedin_indeed", "LinkedIn + Indeed + Google"))

    adapters.append(HackerNewsAdapter())
    display.append(("hackernews", "HackerNews (Who is Hiring)"))

    adapters.append(RemoteOKAdapter())
    display.append(("remoteok", "RemoteOK"))

    wd = companies.get("workday", [])
    if wd:
        adapters.append(WorkdayAdapter(companies=wd))
        display.append(("workday", f"Workday ({len(wd)} co)"))

    return adapters, display, li_adapter


async def _h1b_check_with_timeout(checker: "H1BChecker", jobs: list, timeout: float = 300) -> None:
    """Run H1B check with a wall-clock timeout. On timeout, log and continue with None status."""
    try:
        await asyncio.wait_for(checker.check_batch(jobs), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(
            f"H1B checker timed out after {timeout}s — "
            "all jobs proceeding with h1b_sponsor_verified=None"
        )


async def _fetch_deferred_descriptions(
    label: str,
    jobs_to_fetch: list,
    fetch_coro,
    stage1: Stage1Filter,
    ui: "PipelineUI",
    *, passed_jobs: list, rejected: list, no_desc_passed: list, desc_jobs: list,
) -> tuple[int, int, list]:
    """Fetch descriptions for title-gate survivors missing one, then run
    Stage 1's full filter (description hard-stops + must-have keywords) on
    whichever come back filled, merging survivors into `passed_jobs`.

    `fetch_coro(jobs, on_progress=None) -> int` is either
    sources.workday.fetch_descriptions or
    LinkedInIndeedAdapter.fetch_descriptions — same shape, same pattern.

    Mutates `passed_jobs`, `rejected`, and `desc_jobs` in place (list
    extension). Returns (n_filled, n_promoted, updated_no_desc_passed) since
    filtering `no_desc_passed` down requires rebinding, not mutation.
    """
    if not jobs_to_fetch:
        return 0, 0, no_desc_passed

    with ui.progress(
        f"Fetching {len(jobs_to_fetch)} {label} descriptions",
        total=len(jobs_to_fetch),
    ) as advance:
        n_filled = await fetch_coro(jobs_to_fetch, on_progress=advance)

    filled_jobs = [j for j in jobs_to_fetch if j.description and j.description.strip()]
    n_promoted = 0
    if filled_jobs:
        newly_passed, newly_rejected = stage1.filter_batch(filled_jobs)
        passed_jobs.extend(newly_passed)
        rejected.extend(newly_rejected)
        n_promoted = len(newly_passed)
        # Remove the now-described jobs from no_desc_passed so they don't
        # double up as MAYBE in the Daily tab.
        filled_fps = {j.fingerprint for j in filled_jobs}
        no_desc_passed = [j for j in no_desc_passed if j.fingerprint not in filled_fps]
        # Move their descriptions back into desc_jobs so they get persisted.
        desc_jobs.extend(filled_jobs)

    return n_filled, n_promoted, no_desc_passed


def _dedup_daily_jobs(jobs: list["ScreenedJob"]) -> list["ScreenedJob"]:
    """Deduplicate Daily jobs by fingerprint, keeping the highest-confidence version."""
    seen: set[str] = set()
    result: list["ScreenedJob"] = []
    for job in sorted(jobs, key=lambda j: j.confidence, reverse=True):
        if job.fingerprint not in seen:
            seen.add(job.fingerprint)
            result.append(job)
        else:
            logger.warning(
                f"Dedup: removed duplicate daily entry for {job.company} — {job.title}"
            )
    return result


async def run_pipeline() -> None:
    # Initialize logging + rich console here, not at import time — see the
    # NOTE above TOTAL_PHASES.
    Path("logs").mkdir(exist_ok=True)
    log_path = f"logs/run_{date.today().isoformat()}.log"
    console = install_rich_logging(file_log_path=log_path, level=logging.INFO)

    ui = PipelineUI(total_phases=TOTAL_PHASES, console=console)
    ui.banner(subtitle=f"{date.today().isoformat()}  ·  freshness window: {HOURS_OLD}h")

    # ── Phase 1: Init ─────────────────────────────────────────
    ui.phase(1, "Initializing (profile, DB, Google creds)")
    validate_required_config()
    if not Path("profile.yaml").exists():
        ui.error("profile.yaml not found. Run `python update_profile.py` first.")
        sys.exit(1)

    db = Database(DB_FILE)
    db.initialize()
    sheets = SheetsClient()
    daily_ws = sheets.get_daily_sheet()
    audit_ws = sheets.get_audit_sheet()
    usage_start_id = db.get_max_claude_usage_id()
    # Union of "first seen recently" and "screened recently" — the latter
    # catches long-lived postings from prefiltered sources (LinkedIn/Indeed/
    # Google) that keep resurfacing as "fresh" well past STALE_JOB_DAYS since
    # their first sighting, which previously caused Stage 2 to re-screen the
    # same job daily indefinitely.
    known_fps = db.get_recent_fingerprints(STALE_JOB_DAYS)
    rescreened_fps = db.get_recently_audited_fingerprints(STALE_JOB_DAYS)
    known_fps |= rescreened_fps
    applied_fps = {row["job_fingerprint"] for row in db.get_all_feedback()}
    known_fps |= applied_fps
    ui.phase_done(
        f"{len(known_fps)} known fingerprints "
        f"({len(known_fps) - len(applied_fps)} recent/screened + {len(applied_fps)} applied)"
    )

    # ── Phase 2: Clear sheets ─────────────────────────────────
    ui.phase(2, "Clearing Daily + Audit tabs")
    daily_ops.clear_and_write_headers(daily_ws)
    audit_ops.clear_and_write_headers(audit_ws)
    format_all_sheets(sheets.spreadsheet)
    ui.phase_done()

    # ── Phase 3: Scrape sources (parallel) ────────────────────
    ui.phase(3, "Scraping sources in parallel")
    companies = load_target_companies()
    adapters, display_sources, li_adapter = build_adapters(companies)
    orchestrator = ScraperOrchestrator(adapters)

    with ui.scrape_table(display_sources) as tracker:
        scrape_result = await orchestrator.scrape_all(
            TARGET_TITLES, LOCATIONS,
            known_fingerprints=known_fps,
            on_source_done=tracker.mark_done,
            hours_old=HOURS_OLD,
        )
    all_scraped = scrape_result.jobs
    error_note = f"  ·  {len(scrape_result.errors)} source error(s)" if scrape_result.errors else ""
    ui.phase_done(f"{len(all_scraped)} unique jobs after cross-source + DB dedup{error_note}")

    # Queue any newly discovered Workday tenants for promotion review.
    # Discoveries don't go straight into the active scrape list — they wait
    # in workday_candidates.yaml until promote_workday_candidates.py validates
    # them against h1bdata.info + a live Workday API ping.
    new_wd_queued, new_wd_repeats = save_candidates(
        li_adapter.discovered_workday_companies,
    )
    if new_wd_queued or new_wd_repeats:
        logger.info(
            f"Workday candidates: {new_wd_queued} new queued, "
            f"{new_wd_repeats} repeat sightings — "
            f"run `python scripts/promote_workday_candidates.py` to validate"
        )

    # ── Phase 4: Freshness filter ─────────────────────────────
    ui.phase(4, f"Freshness filter (<= {HOURS_OLD}h old)")
    unique_jobs, stale_jobs = filter_fresh_jobs(all_scraped, HOURS_OLD)
    ui.phase_done(f"kept {len(unique_jobs)}  ·  dropped {len(stale_jobs)} stale")

    # ── Phase 5: H1B Sponsor Check + source-aware drop ───────
    ui.phase(5, "H1B Sponsor Check + source-aware drop")
    sponsor_dropped = []
    if not SPONSORSHIP_FILTER_ENABLED:
        # Candidate is work-authorized and does not need sponsorship yet, so
        # the slow h1bdata.info scrape AND the no-history drop are both skipped.
        # Flip config.SPONSORSHIP_FILTER_ENABLED to re-enable. See config.py.
        ui.phase_done("filter OFF — skipped (work-authorized; reclaims scrape time)")
    else:
        checker = H1BChecker(db)
        await _h1b_check_with_timeout(checker, unique_jobs)
        n_curated = sum(
            1 for j in unique_jobs
            if j.source.startswith(("greenhouse-", "lever-", "ashby-"))
        )
        n_verified = sum(1 for j in unique_jobs if j.h1b_sponsor_verified is True)
        sponsor_kept, sponsor_dropped = partition_drops(unique_jobs)
        n_checked = sum(1 for j in unique_jobs if j.h1b_sponsor_verified is not None)
        n_no_history_kept = sum(
            1 for j in sponsor_kept if j.h1b_sponsor_verified is False
        )
        unique_jobs = sponsor_kept  # rebind for downstream phases

        # Persist dropped jobs to Audit so the funnel is auditable
        if sponsor_dropped:
            today_str = date.today().isoformat()
            h1b_audit_entries = [
                {
                    "job_fingerprint": j.fingerprint,
                    "company": j.company,
                    "title": j.title,
                    "source": j.source,
                    "stage": "stage_h1b",
                    "verdict": "REJECT",
                    "reason": "company has no H-1B sponsorship history",
                    "confidence": None,
                    "run_date": today_str,
                }
                for j in sponsor_dropped
            ]
            db.save_audit_entries_bulk(h1b_audit_entries)

            h1b_drop_results = [
                FilterResult(
                    job=j,
                    passed=False,
                    reason="company has no H-1B sponsorship history",
                    stage="stage_h1b",
                )
                for j in sponsor_dropped
            ]
            audit_ops.write_rejections(audit_ws, h1b_drop_results)

        ui.phase_done(
            f"{n_checked} checked  ·  {n_verified} verified  ·  "
            f"{len(sponsor_dropped)} no-history dropped  ·  "
            f"{n_no_history_kept} no-history kept (startup-friendly)  ·  "
            f"{n_curated} curated skipped"
        )

    # Partition jobs by whether they arrived with descriptions. Sources that
    # return descriptions inline (Greenhouse/Lever/Ashby/HN/RemoteOK + LinkedIn
    # with fetch_description=True) feed the full Stage 1 filter. Sources that
    # don't (Workday) get a title-only Stage 1 pass and surface in Daily as
    # MAYBE for manual review. The previous bulk URL-backfill phase was removed
    # 2026-04-29 — fill rate was ~2% and it dominated runtime.
    desc_jobs = [j for j in unique_jobs if j.description and j.description.strip()]
    no_desc_jobs = [j for j in unique_jobs if not (j.description and j.description.strip())]

    # ── Phase 6: Stage 1 regex filter ─────────────────────
    ui.phase(6, "Stage 1 regex filter")
    stage1 = Stage1Filter()
    passed_jobs, desc_rejected = stage1.filter_batch(desc_jobs)

    # Apply title-only checks to no_desc_jobs so "Senior X" / unrelated titles
    # are routed to Audit instead of cluttering the Daily tab.
    no_desc_passed, no_desc_rejected = stage1.filter_titles_only(no_desc_jobs)
    rejected: list[FilterResult] = list(desc_rejected) + list(no_desc_rejected)

    # Workday and LinkedIn both return no description inline (Workday's search
    # API never has one; LinkedIn's is deferred — see
    # sources/linkedin_indeed.py module docstring). Fetch them now, only for
    # jobs whose titles already cleared filter_titles_only. Survivors get the
    # full Stage 1 pass (description hard-stops + must-have keywords) and
    # merge into passed_jobs so Stage 2 actually screens them.
    wd_to_fetch = [j for j in no_desc_passed if j.source.startswith("workday-")]
    n_wd_filled, n_wd_promoted, no_desc_passed = await _fetch_deferred_descriptions(
        "Workday", wd_to_fetch, fetch_workday_descriptions, stage1, ui,
        passed_jobs=passed_jobs, rejected=rejected,
        no_desc_passed=no_desc_passed, desc_jobs=desc_jobs,
    )

    li_to_fetch = [j for j in no_desc_passed if j.source == "linkedin"]
    n_li_filled, n_li_promoted, no_desc_passed = await _fetch_deferred_descriptions(
        "LinkedIn", li_to_fetch, li_adapter.fetch_descriptions, stage1, ui,
        passed_jobs=passed_jobs, rejected=rejected,
        no_desc_passed=no_desc_passed, desc_jobs=desc_jobs,
    )

    ui.phase_done(
        f"{len(passed_jobs)} passed (incl. {n_wd_promoted} Workday + "
        f"{n_li_promoted} LinkedIn from deferred fetch)  ·  "
        f"{len(desc_rejected)} rejected  ·  "
        f"{len(no_desc_passed)} no-desc title-passed  ·  "
        f"Workday desc filled {n_wd_filled}/{len(wd_to_fetch)}  ·  "
        f"LinkedIn desc filled {n_li_filled}/{len(li_to_fetch)}"
    )

    # ── Phase 7: Persist to SQLite ────────────────────────────
    ui.phase(7, "Persisting to SQLite")
    # Only save jobs that have descriptions — no_desc_jobs are intentionally
    # excluded so their fingerprints don't block re-scraping on future runs.
    # If the listing gains a description tomorrow it will be picked up fresh.
    db.save_jobs(desc_jobs)
    for job in desc_jobs:
        if job.description and job.description.strip():
            db.update_description(job.fingerprint, job.description)

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
    ui.phase_done(f"{len(unique_jobs)} jobs + {len(audit_entries)} audit rows")

    # ── Phase 8: Stage 2 Claude screen ────────────────────────
    ui.phase(8, "Stage 2 Claude CLI precision screen")
    stage2 = Stage2Screen(profile_path="profile.yaml")

    try:
        stage2.validate_cli()
    except RuntimeError as e:
        ui.error(str(e))
        ui.error(
            "Pipeline aborted at Stage 2. Fix the CLI path and re-run. "
            "Phases 1-7 completed successfully; SQLite was updated."
        )
        db.close()
        sys.exit(1)

    if not passed_jobs:
        screened_jobs: list[ScreenedJob] = []
        ui.phase_done("nothing to screen")
    else:
        from config import SCREENING_BATCH_SIZE
        num_batches = (len(passed_jobs) + SCREENING_BATCH_SIZE - 1) // SCREENING_BATCH_SIZE
        with ui.progress(f"Screening {len(passed_jobs)} jobs", total=num_batches) as advance:
            screened_jobs = stage2.screen_batch(passed_jobs, on_progress=advance)

        apply_n = sum(1 for j in screened_jobs if j.verdict == ScreeningVerdict.APPLY)
        maybe_n = sum(1 for j in screened_jobs if j.verdict == ScreeningVerdict.MAYBE)
        skip_n = sum(1 for j in screened_jobs if j.verdict == ScreeningVerdict.SKIP)
        ui.phase_done(f"APPLY {apply_n}  ·  MAYBE {maybe_n}  ·  SKIP {skip_n}")

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

    # ── Phase 9: Write Daily + Audit tabs ────────────────────
    ui.phase(9, "Writing Daily + Audit tabs")
    daily_jobs = [
        j for j in screened_jobs
        if j.verdict in (ScreeningVerdict.APPLY, ScreeningVerdict.MAYBE)
    ]
    for job in no_desc_passed:
        daily_jobs.append(ScreenedJob(
            **job.model_dump(),
            verdict=ScreeningVerdict.MAYBE,
            confidence=1,
            reasoning="No JD available — review link manually",
            match_signals=[],
            risk_flags=["no_description"],
            suggested_angle="",
        ))
    daily_jobs = _dedup_daily_jobs(daily_jobs)
    daily_ops.write_screened_jobs(daily_ws, daily_jobs)

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
    ui.phase_done(f"{len(daily_jobs)} to Daily  ·  {len(rejected) + len(stage2_skips)} to Audit")

    # ── Final summary panel ──────────────────────────────────
    apply_count = sum(1 for j in screened_jobs if j.verdict == ScreeningVerdict.APPLY)
    maybe_count = sum(1 for j in screened_jobs if j.verdict == ScreeningVerdict.MAYBE)
    skip_count = sum(1 for j in screened_jobs if j.verdict == ScreeningVerdict.SKIP)

    top: tuple[str, int] | None = None
    apply_jobs_sorted = sorted(
        (j for j in screened_jobs if j.verdict == ScreeningVerdict.APPLY),
        key=lambda j: j.confidence, reverse=True,
    )
    if apply_jobs_sorted:
        best = apply_jobs_sorted[0]
        top = (f"{best.company} — {best.title}", best.confidence)

    stats = {
        # ── Scrape funnel ──────────────────────────────────────
        "Scraped (all sources)": len(all_scraped),
        f"Fresh (<= {HOURS_OLD}h)": len(unique_jobs) + len(sponsor_dropped),
        "Stale dropped": len(stale_jobs),
        "Dropped (no h1b sponsor)": len(sponsor_dropped),
        # ── Description partition ──────────────────────────────
        "With descriptions": len(desc_jobs),
        "No description (Workday/etc)": len(no_desc_jobs),
        # ── Stage 1 ────────────────────────────────────────────
        "Stage 1 passed": len(passed_jobs),
        "Stage 1 rejected": len(desc_rejected),
        "No-desc title-passed": len(no_desc_passed),
        # ── Stage 2 ────────────────────────────────────────────
        "Stage 2 APPLY": apply_count,
        "Stage 2 MAYBE": maybe_count,
        "Stage 2 SKIP": skip_count,
        # ── Output ─────────────────────────────────────────────
        "Written to Daily": len(daily_jobs),
    }
    if scrape_result.errors:
        stats["Source errors"] = f"{len(scrape_result.errors)} (see log)"

    usage_rows = db.get_claude_usage_since_id(usage_start_id)
    if usage_rows:
        in_tok = sum(r["input_tokens"] for r in usage_rows)
        out_tok = sum(r["output_tokens"] for r in usage_rows)
        cache_read = sum(r["cache_read_input_tokens"] for r in usage_rows)
        cost = sum(r["cost_usd"] or 0 for r in usage_rows)
        stats["Claude usage (Stage 2)"] = (
            f"{len(usage_rows)} call(s) · {in_tok + out_tok:,} tok "
            f"({cache_read:,} cache-read) · ~${cost:.2f} est."
        )

    ui.summary(stats, top_apply=top, log_path=log_path)
    ui.console.print(
        "     [dim]Cost is a local estimate, not a bill (Max plan). "
        "Run `python usage_report.py` for cumulative usage, or `/usage` "
        "inside an interactive `claude` session for your plan's rate-limit %.[/dim]"
    )

    db.close()


def main() -> None:
    asyncio.run(run_pipeline())


if __name__ == "__main__":
    main()
