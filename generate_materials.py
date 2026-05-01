"""
============================================================
  GENERATE MATERIALS — Resume + Cover Letter Automation
============================================================
  Reads Apply jobs from Daily tab, generates tailored resume
  + cover letter for each via a single Claude CLI call,
  uploads to Drive (or saves locally), records in Applied tab.
============================================================
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path

from config import DB_FILE, YOUR_NAME, GOOGLE_DRIVE_FOLDER_ID
from db.database import Database
from sources.backfill import fetch_description_from_url
from generation.resume_engine import ResumeEngine
from generation.pdf_renderer import render_resume_pdf, render_cover_letter_pdf
from generation.drive_uploader import DriveUploader
from models.job import ScreenedJob, ScreeningVerdict
from sheets.client import SheetsClient
from sheets import daily as daily_ops, materials as materials_ops
from sheets.formatting import format_all_sheets

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Quiet third-party noise. WARNING+ from our own code still surfaces.
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
for _noisy in ("fontTools", "fontTools.subset", "fontTools.ttLib", "fontTools.ttLib.ttFont",
               "googleapiclient", "googleapiclient.discovery_cache",
               "weasyprint", "weasyprint.progress", "google", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

BAR = "─" * 68


def slugify(text: str) -> str:
    return text.lower().replace(" ", "-").replace(",", "").replace(".", "")[:50]


def fmt_dur(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m {s}s"


def step(label: str):
    """Print '  ├─ <label>...' inline; return a closure to print the result."""
    print(f"  ├─ {label}... ", end="", flush=True)
    t0 = time.perf_counter()

    def done(msg: str = "done", ok: bool = True):
        elapsed = time.perf_counter() - t0
        symbol = "✓" if ok else "✗"
        print(f"{symbol} {msg} ({fmt_dur(elapsed)})")
        return elapsed

    return done


def print_header(num_jobs: int, drive_enabled: bool, started_at: datetime) -> None:
    print()
    print("=" * 68)
    print("  GENERATE MATERIALS — Resume + Cover Letter")
    print("=" * 68)
    print(f"  Jobs queued:   {num_jobs} (marked 'Apply' in Daily tab)")
    print(f"  Drive uploads: {'enabled' if drive_enabled else 'DISABLED — using local file paths'}")
    print(f"  Output dir:    {Path('output').resolve()}")
    print(f"  Started:       {started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 68)
    print()


def print_summary(counters: dict, total_elapsed: float, drive_enabled: bool) -> None:
    total = sum(counters.values())
    print()
    print("=" * 68)
    print("  SUMMARY")
    print("=" * 68)
    print(f"  Processed:        {total}")
    print(f"  ✓ Ready to Apply:  {counters['success']}")
    if not drive_enabled or counters['local_only'] > 0:
        print(f"  ⓘ Local PDFs only: {counters['local_only']}")
    if counters['pdf_failed'] > 0:
        print(f"  ⚠ PDF render failed: {counters['pdf_failed']} (HTML fallbacks written)")
    if counters['claude_failed'] > 0:
        print(f"  ✗ Claude failed:   {counters['claude_failed']}")
    if counters.get('already_done', 0) > 0:
        print(f"  ↩ Already done:    {counters['already_done']} (skipped)")
    print(f"  ⏱ Total time:      {fmt_dur(total_elapsed)}")
    print(f"  📂 PDFs at:        {Path('output').resolve()}")
    print(f"  📋 Next step:      open Applied tab in Google Sheets")
    print("=" * 68)
    print()


def process_job(
    *, idx: int, total: int, row: dict, today: str,
    db: Database, engine: ResumeEngine, uploader: DriveUploader | None,
    applied_ws,
) -> str:
    """Process one job. Returns one of: success, local_only, pdf_failed, claude_failed."""
    company = row.get("Company", "")
    title = row.get("Job Title", "")
    location = row.get("Location", "")
    source = row.get("Source", "")
    confidence = row.get("Confidence", 3)
    reasoning = row.get("AI Reasoning", "")
    suggested_angle = row.get("Suggested Angle", "")
    apply_link = row.get("Apply Link", "")

    job_t0 = time.perf_counter()
    print(f"[{idx}/{total}] {company} · {title} · {location or '—'}")

    # ── Step 1: load description ──────────────────────────
    fingerprint = f"{company.strip().lower()}||{title.strip().lower()}"
    finish = step("Loading description from DB")
    description = db.get_description_by_fingerprint(fingerprint) or ""
    finish(f"{len(description)} chars" if description else "not in DB")

    if not description.strip() and apply_link.strip():
        finish = step("Fetching description from job URL")
        try:
            fetched = asyncio.run(fetch_description_from_url(apply_link))
        except Exception as e:
            fetched = None
            finish(f"fetch error ({type(e).__name__})", ok=False)
        else:
            if fetched:
                description = fetched
                db.update_description(fingerprint, description)
                finish(f"{len(description)} chars saved to DB")
            else:
                finish("no content (resume will be generic)", ok=False)

    # ── Step 2: Claude generates resume + cover letter ────
    finish = step("Generating resume + cover letter via Claude")
    result = engine.generate(
        company=company, title=title, location=location,
        description=description, source=source,
        screening_notes=f"Angle: {suggested_angle}. {reasoning}",
    )
    if not result:
        finish("Claude returned no result", ok=False)
        print(f"  └─ ✗ SKIPPED — generation failed\n")
        return "claude_failed"
    finish(f"angle: {result.get('decisions', {}).get('angle', '?')[:40]}")

    # ── Step 3: render PDFs ───────────────────────────────
    company_slug = slugify(company)
    role_slug = slugify(title)
    output_dir = Path("output") / company_slug / f"{today}_{role_slug}"
    output_dir.mkdir(parents=True, exist_ok=True)
    resume_path = output_dir / f"{YOUR_NAME.replace(' ', '_')}_Resume.pdf"
    cl_path = output_dir / f"{YOUR_NAME.replace(' ', '_')}_Cover_Letter.pdf"

    finish = step("Rendering resume PDF")
    resume_ok = render_resume_pdf(result, resume_path)
    finish("written" if resume_ok else "FAILED — see .html fallback", ok=resume_ok)

    finish = step("Rendering cover letter PDF")
    cl_ok = render_cover_letter_pdf(
        result.get("cover_letter", ""), company, title, cl_path,
        location=result.get("resume", {}).get("personal", {}).get("location", "") or location,
        today=date.today(),
    )
    finish("written" if cl_ok else "FAILED — see .html fallback", ok=cl_ok)

    metadata_path = output_dir / "_metadata.json"
    metadata_path.write_text(json.dumps({
        "job": {"company": company, "title": title, "source": source, "confidence": confidence},
        "decisions": result.get("decisions", {}),
        "generated_at": today,
    }, indent=2))

    # ── Step 4: Drive upload (if enabled) ─────────────────
    resume_link = ""
    cl_link = ""
    drive_failure_msg = ""
    if uploader is not None:
        finish = step("Uploading to Google Drive")
        try:
            company_folder = uploader.get_or_create_folder(company_slug)
            role_folder = uploader.get_or_create_folder(f"{today}_{role_slug}", company_folder)
            if resume_ok:
                resume_link = uploader.upload_file(resume_path, role_folder, resume_path.name)
            if cl_ok:
                cl_link = uploader.upload_file(cl_path, role_folder, cl_path.name)
            finish("uploaded")
        except Exception as e:
            drive_failure_msg = f"{type(e).__name__}: {str(e)[:120]}"
            finish(f"FAILED — {drive_failure_msg}", ok=False)

    if not resume_link and resume_ok:
        resume_link = str(resume_path.resolve())
    if not cl_link and cl_ok:
        cl_link = str(cl_path.resolve())

    # ── Step 5: classify outcome + write to Sheet ─────────
    notes_parts = []
    if not resume_ok:
        notes_parts.append(f"Resume PDF render FAILED — see {resume_path.with_suffix('.html')}")
    if not cl_ok:
        notes_parts.append(f"Cover letter PDF render FAILED — see {cl_path.with_suffix('.html')}")
    if drive_failure_msg:
        notes_parts.append(f"Drive upload failed ({drive_failure_msg})")
    notes = " | ".join(notes_parts)

    if not resume_ok or not cl_ok:
        status = "PDF Render Failed"
        outcome = "pdf_failed"
        outcome_symbol, outcome_msg = "⚠", "PDF render failed"
    else:
        status = "Ready to Apply"
        outcome = "success" if (uploader and not drive_failure_msg) else "local_only"
        outcome_symbol, outcome_msg = "✓", "uploaded to Drive" if outcome == "success" else "local PDFs ready"

    finish = step("Recording in Applied tab")
    screened = ScreenedJob(
        title=title, company=company, location=location,
        description="", url=apply_link, source=source,
        verdict=ScreeningVerdict.APPLY, confidence=int(confidence),
        reasoning=reasoning, suggested_angle=suggested_angle,
    )
    materials_ops.add_job(
        applied_ws, screened,
        resume_link=resume_link, cover_letter_link=cl_link,
        angle_used=result.get("decisions", {}).get("angle", suggested_angle),
        notes=notes, status=status,
    )
    db.save_feedback(
        job_fingerprint=fingerprint,
        company=company, title=title, source=source,
        screen_confidence=int(confidence),
        resume_angle=result.get("decisions", {}).get("angle", ""),
        date_applied=today,
    )
    finish(f"row written")

    job_elapsed = time.perf_counter() - job_t0
    print(f"  └─ {outcome_symbol} {outcome_msg} · job time: {fmt_dur(job_elapsed)}")
    print()
    return outcome


def main():
    started_at = datetime.now()
    overall_t0 = time.perf_counter()

    db = Database(DB_FILE)
    db.initialize()

    sheets = SheetsClient()
    daily_ws = sheets.get_daily_sheet()
    applied_ws = sheets.get_materials_sheet()
    try:
        format_all_sheets(sheets.spreadsheet)
    except Exception as e:
        logger.warning(f"Sheet formatting failed (continuing): {e}")

    apply_jobs = daily_ops.get_apply_jobs(daily_ws)
    if not apply_jobs:
        print("\nNo jobs marked 'Apply' in the Daily tab. Nothing to do.\n")
        db.close()
        return

    drive_enabled = bool(GOOGLE_DRIVE_FOLDER_ID)
    print_header(len(apply_jobs), drive_enabled, started_at)

    already_done = materials_ops.get_generated_fingerprints(applied_ws)

    engine = ResumeEngine(profile_path="profile.yaml")
    uploader = DriveUploader() if drive_enabled else None
    today = date.today().isoformat()

    counters = {"success": 0, "local_only": 0, "pdf_failed": 0, "claude_failed": 0, "already_done": 0}

    try:
        for i, row in enumerate(apply_jobs, 1):
            company = row.get("Company", "")
            title = row.get("Job Title", "")
            fingerprint = f"{company.strip().lower()}||{title.strip().lower()}"
            if fingerprint in already_done:
                print(f"[{i}/{len(apply_jobs)}] {company} · {title} — already generated, skipping\n")
                counters["already_done"] += 1
                continue
            try:
                outcome = process_job(
                    idx=i, total=len(apply_jobs), row=row, today=today,
                    db=db, engine=engine, uploader=uploader, applied_ws=applied_ws,
                )
                counters[outcome] = counters.get(outcome, 0) + 1
            except Exception as e:
                counters["claude_failed"] = counters.get("claude_failed", 0) + 1
                print(f"  └─ ✗ UNEXPECTED ERROR: {type(e).__name__}: {e}\n")
                logger.exception("Unexpected error processing job")
    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted by user. Progress so far is saved in the Materials tab + DB.\n")
    finally:
        db.close()

    total_elapsed = time.perf_counter() - overall_t0
    print_summary(counters, total_elapsed, drive_enabled)


if __name__ == "__main__":
    main()
