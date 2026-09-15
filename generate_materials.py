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
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

from config import (
    DB_FILE, YOUR_NAME, GOOGLE_DRIVE_FOLDER_ID,
    RESUME_VERIFICATION_ENABLED, RESUME_INTERVIEW_SCORE_THRESHOLD,
    RESUME_MAX_REVISIONS,
)
from db.database import Database
from sources.backfill import fetch_description_from_url
from generation.resume_engine import ResumeEngine
from generation.verifier import ResumeVerifier, format_feedback, keyword_coverage
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
    import re
    text = text.lower()
    text = re.sub(r'[\\/:*?"<>|()\[\]{}]', "", text)  # strip Windows-invalid + brackets
    text = re.sub(r'\s+', "-", text.strip())
    text = re.sub(r'-+', "-", text)
    return text[:50].rstrip("-")


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


def print_header(num_jobs: int, drive_enabled: bool, started_at: datetime, workers: int = 1) -> None:
    print()
    print("=" * 68)
    print("  GENERATE MATERIALS — Resume + Cover Letter")
    print("=" * 68)
    print(f"  Jobs queued:   {num_jobs} (marked 'Apply' in Daily tab)")
    print(f"  Parallel:      {workers} concurrent worker{'s' if workers != 1 else ''}")
    print(f"  Drive uploads: {'enabled' if drive_enabled else 'DISABLED — using local file paths'}")
    print(f"  Output dir:    {Path('output').resolve()}")
    print(f"  Started:       {started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 68)
    print()


def print_summary(
    counters: dict, total_elapsed: float, drive_enabled: bool,
    usage_rows: list[dict] | None = None,
) -> None:
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
    if usage_rows:
        in_tok = sum(r["input_tokens"] for r in usage_rows)
        out_tok = sum(r["output_tokens"] for r in usage_rows)
        cache_read = sum(r["cache_read_input_tokens"] for r in usage_rows)
        cost = sum(r["cost_usd"] or 0 for r in usage_rows)
        print(
            f"  🤖 Claude usage:   {len(usage_rows)} call(s) · {in_tok + out_tok:,} tok "
            f"({cache_read:,} cache-read) · ~${cost:.2f} est. (Max plan — not billed)"
        )
        print(f"     Full breakdown: python usage_report.py  ·  rate-limit %: /usage in `claude`")
    print(f"  📋 Next step:      open Applied tab in Google Sheets")
    print("=" * 68)
    print()


class StatusBoard:
    """Thread-safe live status board for parallel job generation.

    Maintains one line per active job in the terminal, erasing and redrawing on
    every state change so the user always sees what each worker is doing.
    Falls back to plain prefixed lines when stdout is not a tty (CI, piped).
    """

    _STEP_W = 24   # chars reserved for the current-step column
    _JOB_W  = 54   # chars reserved for the job-label column

    def __init__(self, total: int):
        self._lock = threading.Lock()
        self._total = total
        self._active: dict[int, dict] = {}   # idx -> {prefix, step, t0}
        self._board_lines = 0
        self._ansi = sys.stdout.isatty()
        if self._ansi and sys.platform == "win32":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            except Exception:
                self._ansi = False

    def start(self, idx: int, company: str, title: str, location: str = "") -> None:
        loc = f" · {location}" if location else ""
        prefix = f"[{idx}/{self._total}] {company} · {title}{loc}"
        with self._lock:
            self._active[idx] = {"prefix": prefix, "step": "starting", "t0": time.perf_counter()}
            if self._ansi:
                self._redraw_locked()
            else:
                print(f"  → {prefix}", flush=True)

    def update(self, idx: int, step: str) -> None:
        with self._lock:
            if idx in self._active:
                self._active[idx]["step"] = step
            if self._ansi:
                self._redraw_locked()

    def complete(self, idx: int, line: str) -> None:
        with self._lock:
            self._active.pop(idx, None)
            if self._ansi:
                self._erase_locked()
                print(line, flush=True)
                self._redraw_locked()
            else:
                print(line, flush=True)

    def _erase_locked(self) -> None:
        if self._board_lines:
            sys.stdout.write(f"\033[{self._board_lines}A\033[J")
            sys.stdout.flush()
            self._board_lines = 0

    def _redraw_locked(self) -> None:
        self._erase_locked()
        if not self._active:
            return
        lines = []
        for idx, info in sorted(self._active.items()):
            elapsed = fmt_dur(time.perf_counter() - info["t0"])
            prefix = info["prefix"][:self._JOB_W]
            step   = (info["step"] + "...")[:self._STEP_W]
            lines.append(f"  ⟳ {prefix:<{self._JOB_W}}  {step:<{self._STEP_W}}  {elapsed:>7}")
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()
        self._board_lines = len(lines)


def _verify_and_improve(
    *, engine: ResumeEngine, verifier: ResumeVerifier, base: dict,
    company: str, title: str, location: str, description: str,
    source: str, screening_notes: str,
) -> dict:
    """Score the draft with the recruiter sim and regenerate up to
    RESUME_MAX_REVISIONS times, keeping the highest interview-likelihood
    version. Returns the chosen result annotated with '_verification' and
    '_interview_score'. A failed/timed-out verification keeps the current draft."""
    best = base
    best_score = -1.0
    best_vr = None
    current = base
    attempts = 1 + RESUME_MAX_REVISIONS

    for attempt in range(1, attempts + 1):
        jd_keywords = (current.get("decisions", {}) or {}).get("jd_top_keywords", []) or []
        finish = step(f"Recruiter-sim verify (attempt {attempt}/{attempts})")
        vr = verifier.verify(
            resume_data=current, cover_letter=current.get("cover_letter", ""),
            company=company, title=title, location=location,
            description=description, jd_keywords=jd_keywords,
        )
        if not vr:
            finish("verify failed — keeping current draft", ok=False)
            break

        score = float(vr.get("interview_likelihood", 0) or 0)
        verdict = str(vr.get("verdict", ""))
        finish(f"score {score:.0f}/100 · {verdict}")
        if score > best_score:
            best, best_score, best_vr = current, score, vr

        if score >= RESUME_INTERVIEW_SCORE_THRESHOLD or verdict == "ship":
            break
        if attempt == attempts:
            break  # revision budget exhausted

        feedback = format_feedback(vr)
        finish2 = step(f"Regenerating with {len(vr.get('fixes', []) or [])} fixes")
        revised = engine.generate(
            company=company, title=title, location=location,
            description=description, source=source,
            screening_notes=screening_notes, revision_feedback=feedback,
        )
        if not revised:
            finish2("regeneration failed — keeping best so far", ok=False)
            break
        finish2("done")
        current = revised

    if best_vr is not None:
        best["_verification"] = best_vr
        best["_interview_score"] = best_score
    return best


def process_job(
    *, idx: int, total: int, row: dict, today: str,
    drive_enabled: bool, engine: ResumeEngine, verifier: ResumeVerifier,
    applied_ws, sheets_lock: threading.Lock, board: StatusBoard,
) -> str:
    """Process one job. Returns one of: success, local_only, pdf_failed, claude_failed."""
    # Each worker opens its own SQLite connection (sqlite3 objects are not thread-safe across threads).
    # DriveUploader builds on httplib2 which is also not thread-safe for shared instances.
    db = Database(DB_FILE)
    db.initialize()
    uploader = DriveUploader() if drive_enabled else None
    company = row.get("Company", "")
    title = row.get("Job Title", "")
    location = row.get("Location", "")
    source = row.get("Source", "")
    confidence = row.get("Confidence", 3)
    reasoning = row.get("AI Reasoning", "")
    suggested_angle = row.get("Suggested Angle", "")
    apply_link = row.get("Apply Link", "")

    job_t0 = time.perf_counter()
    board.start(idx, company, title, location)

    # ── Step 1: load description ──────────────────────────
    fingerprint = f"{company.strip().lower()}||{title.strip().lower()}"
    board.update(idx, "loading description")
    description = db.get_description_by_fingerprint(fingerprint) or ""

    if not description.strip() and apply_link.strip():
        board.update(idx, "fetching description")
        try:
            fetched = asyncio.run(fetch_description_from_url(apply_link))
        except Exception:
            fetched = None
        if fetched:
            description = fetched
            db.update_description(fingerprint, description)

    # ── Step 2: Claude generates resume + cover letter ────
    board.update(idx, "generating via Claude")
    result = engine.generate(
        company=company, title=title, location=location,
        description=description, source=source,
        screening_notes=f"Angle: {suggested_angle}. {reasoning}",
    )
    if not result:
        elapsed = fmt_dur(time.perf_counter() - job_t0)
        board.complete(idx, f"  ✗ [{idx}/{total}] {company} · {title}  ·  Claude returned no result  ·  {elapsed}")
        db.close()
        return "claude_failed"

    # ── Step 2b: quality signal ────────────────────────────
    # Verification loop is disabled (too slow: 3-4 Sonnet calls per job).
    # Instead: free local keyword-coverage using the keywords the generation
    # already extracted into decisions.jd_top_keywords — no Claude call.
    if RESUME_VERIFICATION_ENABLED:
        result = _verify_and_improve(
            engine=engine, verifier=verifier, base=result,
            company=company, title=title, location=location,
            description=description, source=source,
            screening_notes=f"Angle: {suggested_angle}. {reasoning}",
        )
    else:
        jd_kws = (result.get("decisions") or {}).get("jd_top_keywords") or []
        if jd_kws:
            board.update(idx, "keyword check")
            cov, missing = keyword_coverage(result, jd_kws)
            result["_interview_score"] = round(cov * 100)
    interview_score = result.get("_interview_score")

    # ── Step 3: render PDFs ───────────────────────────────
    board.update(idx, "rendering PDFs")
    company_slug = slugify(company)
    role_slug = slugify(title)
    output_dir = Path("output") / company_slug / f"{today}_{role_slug}"
    output_dir.mkdir(parents=True, exist_ok=True)
    resume_path = output_dir / f"{YOUR_NAME.replace(' ', '_')}_Resume.pdf"
    cl_path = output_dir / f"{YOUR_NAME.replace(' ', '_')}_Cover_Letter.pdf"

    resume_ok = render_resume_pdf(result, resume_path)
    cl_ok = render_cover_letter_pdf(
        result.get("cover_letter", ""), company, title, cl_path,
        location=result.get("resume", {}).get("personal", {}).get("location", "") or location,
        today=date.today(),
    )

    metadata_path = output_dir / "_metadata.json"
    metadata_path.write_text(json.dumps({
        "job": {"company": company, "title": title, "source": source, "confidence": confidence},
        "decisions": result.get("decisions", {}),
        "interview_score": interview_score,
        "verification": result.get("_verification"),
        "generated_at": today,
    }, indent=2))

    # ── Step 4: Drive upload (if enabled) ─────────────────
    resume_link = ""
    cl_link = ""
    drive_failure_msg = ""
    if uploader is not None:
        board.update(idx, "uploading to Drive")
        try:
            company_folder = uploader.get_or_create_folder(company_slug)
            role_folder = uploader.get_or_create_folder(f"{today}_{role_slug}", company_folder)
            if resume_ok:
                resume_link = uploader.upload_file(resume_path, role_folder, resume_path.name)
            if cl_ok:
                cl_link = uploader.upload_file(cl_path, role_folder, cl_path.name)
        except Exception as e:
            drive_failure_msg = f"{type(e).__name__}: {str(e)[:120]}"

    if not resume_link and resume_ok:
        resume_link = str(resume_path.resolve())
    if not cl_link and cl_ok:
        cl_link = str(cl_path.resolve())

    # ── Step 5: classify outcome + write to Sheet ─────────
    notes_parts = []
    if interview_score is not None:
        notes_parts.append(f"Interview score: {interview_score:.0f}/100")
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

    board.update(idx, "recording in Sheets")
    screened = ScreenedJob(
        title=title, company=company, location=location,
        description="", url=apply_link, source=source,
        verdict=ScreeningVerdict.APPLY, confidence=int(confidence),
        reasoning=reasoning, suggested_angle=suggested_angle,
    )
    with sheets_lock:
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

    elapsed = fmt_dur(time.perf_counter() - job_t0)
    score_str = f"  ·  {interview_score:.0f}/100" if interview_score is not None else ""
    board.complete(
        idx,
        f"  {outcome_symbol} [{idx}/{total}] {company} · {title}  ·  {outcome_msg}{score_str}  ·  {elapsed}",
    )
    db.close()
    return outcome


def main():
    started_at = datetime.now()
    overall_t0 = time.perf_counter()

    # Initialize schema on the main thread; each worker opens its own connection.
    _db = Database(DB_FILE)
    _db.initialize()
    usage_start_id = _db.get_max_claude_usage_id()
    _db.close()

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
        return

    drive_enabled = bool(GOOGLE_DRIVE_FOLDER_ID)
    already_done = materials_ops.get_generated_fingerprints(applied_ws)

    engine = ResumeEngine(profile_path="profile.yaml")
    verifier = ResumeVerifier()
    today = date.today().isoformat()
    sheets_lock = threading.Lock()

    counters = {"success": 0, "local_only": 0, "pdf_failed": 0, "claude_failed": 0, "already_done": 0}

    pending: list[tuple[int, dict]] = []
    for i, row in enumerate(apply_jobs, 1):
        company = row.get("Company", "")
        title = row.get("Job Title", "")
        fingerprint = f"{company.strip().lower()}||{title.strip().lower()}"
        if fingerprint in already_done:
            print(f"  ↩ [{i}/{len(apply_jobs)}] {company} · {title} — already generated, skipping")
            counters["already_done"] += 1
            continue
        pending.append((i, row))

    workers = min(5, len(pending) or 1)
    board = StatusBoard(len(apply_jobs))
    print_header(len(apply_jobs), drive_enabled, started_at, workers=workers)

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    process_job,
                    idx=i, total=len(apply_jobs), row=row, today=today,
                    drive_enabled=drive_enabled, engine=engine, verifier=verifier,
                    applied_ws=applied_ws, sheets_lock=sheets_lock, board=board,
                ): (i, row.get("Company", ""), row.get("Job Title", ""))
                for i, row in pending
            }
            for future in as_completed(futures):
                try:
                    outcome = future.result()
                except Exception as e:
                    idx_val, company, title = futures[future]
                    counters["claude_failed"] = counters.get("claude_failed", 0) + 1
                    print(f"  └─ ✗ UNEXPECTED ERROR [{idx_val}] ({company} · {title}): {type(e).__name__}: {e}\n")
                    logger.exception("Unexpected error processing job")
                else:
                    counters[outcome] = counters.get(outcome, 0) + 1
    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted by user. Progress so far is saved in the Materials tab + DB.\n")

    total_elapsed = time.perf_counter() - overall_t0
    _db = Database(DB_FILE)
    _db.initialize()
    usage_rows = _db.get_claude_usage_since_id(usage_start_id)
    _db.close()
    print_summary(counters, total_elapsed, drive_enabled, usage_rows=usage_rows)


if __name__ == "__main__":
    main()
