"""
Locally-hosted web UI — submit jobs manually through the screening + generation pipeline.

Usage:
    python web_app.py
    Open http://localhost:8765
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from config import DB_FILE, GOOGLE_DRIVE_FOLDER_ID, SPONSORSHIP_FILTER_ENABLED, YOUR_NAME
from db.database import Database
from generation.drive_uploader import DriveUploader
from generation.pdf_renderer import render_cover_letter_pdf, render_resume_pdf
from generation.resume_engine import ResumeEngine
from generation.verifier import keyword_coverage
from models.job import RawJob, ScreenedJob, ScreeningVerdict
from screening.h1b_checker import H1BChecker, is_droppable_source
from screening.stage1 import Stage1Filter
from screening.stage2 import Stage2Screen
from sheets import materials as materials_ops
from sheets.client import SheetsClient
from sources.backfill import fetch_description_from_url

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.WARNING)

app = FastAPI(title="Job Pipeline UI")
_executor = ThreadPoolExecutor(max_workers=2)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _slugify(text: str) -> str:
    import re
    text = re.sub(r'[\\/:*?"<>|()\[\]{}]', "", text.lower())
    text = re.sub(r"\s+", "-", text.strip())
    return re.sub(r"-+", "-", text)[:50].rstrip("-")


class JobInput(BaseModel):
    url: str = ""
    title: str
    company: str
    location: str
    description: str = ""
    salary_max: int | None = None
    source: str = "manual"


class GenerateInput(BaseModel):
    title: str
    company: str
    location: str
    url: str = ""
    source: str = "manual"
    description: str = ""
    confidence: int = 3
    reasoning: str = ""
    suggested_angle: str = ""
    h1b_sponsor_verified: bool | None = None


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(
        (Path(__file__).parent / "templates" / "job_ui.html").read_text(encoding="utf-8")
    )


@app.post("/api/screen")
async def screen_job(job_input: JobInput):
    async def stream() -> AsyncGenerator[str, None]:
        loop = asyncio.get_event_loop()
        yield _sse({"type": "status", "message": "Pipeline starting..."})

        # ── 1. Fetch description if not provided ─────────────────────────────
        description = job_input.description.strip()
        if not description and job_input.url.startswith("http"):
            yield _sse({"type": "status", "message": "Fetching description from URL..."})
            try:
                fetched = await fetch_description_from_url(job_input.url)
                if fetched and len(fetched.strip()) > 50:
                    description = fetched
                    yield _sse({
                        "type": "status",
                        "message": f"Description fetched ({len(description):,} chars)",
                    })
                else:
                    yield _sse({
                        "type": "status",
                        "message": "Could not auto-fetch description — Stage 1 keyword checks will fail without it",
                    })
            except Exception as exc:
                yield _sse({"type": "status", "message": f"Fetch error: {exc}"})

        raw_job = RawJob(
            title=job_input.title.strip(),
            company=job_input.company.strip(),
            location=job_input.location.strip(),
            description=description or None,
            salary_max=job_input.salary_max,
            url=job_input.url or "https://example.com",
            source=job_input.source or "manual",
        )

        # ── 1b. Persist to jobs table so main pipeline won't re-surface it ───
        try:
            db_persist = Database(DB_FILE)
            db_persist.initialize()
            already_known = db_persist.fingerprint_exists(raw_job.fingerprint)
            db_persist.save_jobs([raw_job])
            db_persist.close()
            if already_known:
                yield _sse({"type": "status", "message": f"Already in DB ({raw_job.fingerprint}) — updating and re-screening"})
            else:
                yield _sse({"type": "status", "message": "Saved to DB — main pipeline will skip this job going forward"})
        except Exception as exc:
            yield _sse({"type": "status", "message": f"DB save warning: {exc}"})

        # ── 2. H1B check ─────────────────────────────────────────────────────
        yield _sse({"type": "stage_start", "stage": "h1b"})
        try:
            db = Database(DB_FILE)
            db.initialize()
            checker = H1BChecker(db)
            await checker.check_batch([raw_job])
            db.close()
            v = raw_job.h1b_sponsor_verified
            if v is True:
                detail, outcome = "H1B sponsor history found", "verified"
            elif v is False:
                droppable = is_droppable_source(raw_job.source)
                detail = "No H1B history found" + (
                    " — would be dropped in main pipeline" if droppable else " (source not in drop bucket)"
                )
                outcome = "dropped" if droppable else "warn"
            else:
                detail, outcome = "Check unavailable (curated source or network error)", "skipped"
        except Exception as exc:
            detail, outcome = f"H1B check error: {exc}", "skipped"
        yield _sse({"type": "stage_result", "stage": "h1b", "outcome": outcome, "detail": detail})

        # ── 3. Stage 1 ───────────────────────────────────────────────────────
        yield _sse({"type": "stage_start", "stage": "stage1"})
        s1_result = await loop.run_in_executor(_executor, Stage1Filter().filter_job, raw_job)
        yield _sse({
            "type": "stage_result",
            "stage": "stage1",
            "outcome": "passed" if s1_result.passed else "failed",
            "detail": s1_result.reason,
            "sub_stage": s1_result.stage,
        })

        if not s1_result.passed:
            yield _sse({"type": "screening_done", "verdict": "SKIP", "stage1_fail": s1_result.reason})
            return

        # ── 4. Stage 2 ───────────────────────────────────────────────────────
        yield _sse({"type": "stage_start", "stage": "stage2"})
        s2 = Stage2Screen()
        try:
            screened_list = await loop.run_in_executor(
                _executor, lambda: s2.screen_batch([raw_job])
            )
            screened = screened_list[0]
        except Exception as exc:
            yield _sse({"type": "error", "message": f"Stage 2 failed: {exc}"})
            return

        yield _sse({
            "type": "stage_result",
            "stage": "stage2",
            "outcome": (
                "apply" if screened.verdict == ScreeningVerdict.APPLY else
                "maybe" if screened.verdict == ScreeningVerdict.MAYBE else "skip"
            ),
            "verdict": screened.verdict.value,
            "confidence": screened.confidence,
        })
        yield _sse({
            "type": "screening_done",
            "verdict": screened.verdict.value,
            "confidence": screened.confidence,
            "reasoning": screened.reasoning,
            "match_signals": screened.match_signals,
            "risk_flags": screened.risk_flags,
            "suggested_angle": screened.suggested_angle,
            "h1b_sponsor_verified": raw_job.h1b_sponsor_verified,
            "description": description,
        })

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/generate")
async def generate_materials(inp: GenerateInput):
    async def stream() -> AsyncGenerator[str, None]:
        loop = asyncio.get_event_loop()
        today = date.today().isoformat()
        drive_enabled = bool(GOOGLE_DRIVE_FOLDER_ID)

        yield _sse({"type": "gen_progress", "step": "init", "message": "Initializing generation engine..."})

        # ── Generate resume + cover letter ───────────────────────────────────
        yield _sse({
            "type": "gen_progress", "step": "generating",
            "message": "Generating resume + cover letter via Claude (60–120s)...",
        })
        engine = ResumeEngine(profile_path="profile.yaml")
        screening_notes = (
            f"Angle: {inp.suggested_angle}. {inp.reasoning}" if inp.suggested_angle else inp.reasoning
        )
        try:
            result = await loop.run_in_executor(
                _executor,
                lambda: engine.generate(
                    company=inp.company, title=inp.title, location=inp.location,
                    description=inp.description, source=inp.source,
                    screening_notes=screening_notes,
                ),
            )
        except Exception as exc:
            yield _sse({"type": "error", "message": f"Generation failed: {exc}"})
            return

        if not result:
            yield _sse({"type": "error", "message": "Claude returned no result — check CLI logs"})
            return

        # Free local quality signal — same keyword-coverage check generate_materials.py uses
        # (no extra Claude call). Sets result["_interview_score"] for the UI score pill.
        jd_kws = (result.get("decisions") or {}).get("jd_top_keywords") or []
        if jd_kws:
            cov, _missing = keyword_coverage(result, jd_kws)
            result["_interview_score"] = round(cov * 100)

        yield _sse({"type": "gen_progress", "step": "generated", "message": "Resume + cover letter generated"})

        # ── Render PDFs ──────────────────────────────────────────────────────
        yield _sse({"type": "gen_progress", "step": "pdf", "message": "Rendering PDFs..."})
        company_slug = _slugify(inp.company)
        role_slug = _slugify(inp.title)
        output_dir = Path("output") / company_slug / f"{today}_{role_slug}"
        output_dir.mkdir(parents=True, exist_ok=True)

        name_slug = YOUR_NAME.replace(" ", "_")
        resume_path = output_dir / f"{name_slug}_Resume.pdf"
        cl_path = output_dir / f"{name_slug}_Cover_Letter.pdf"

        resume_ok = await loop.run_in_executor(_executor, render_resume_pdf, result, resume_path)
        cl_location = (result.get("resume") or {}).get("personal", {}).get("location", "") or inp.location
        cl_ok = await loop.run_in_executor(
            _executor,
            lambda: render_cover_letter_pdf(
                result.get("cover_letter", ""), inp.company, inp.title, cl_path,
                location=cl_location, today=date.today(),
            ),
        )

        if resume_ok and cl_ok:
            yield _sse({"type": "gen_progress", "step": "pdf_done", "message": "PDFs rendered successfully"})
        else:
            yield _sse({"type": "gen_progress", "step": "pdf_warn",
                        "message": "PDF rendering had issues — HTML fallbacks written to output/"})

        # ── Drive upload ─────────────────────────────────────────────────────
        resume_link = ""
        cl_link = ""
        if drive_enabled:
            yield _sse({"type": "gen_progress", "step": "drive", "message": "Uploading to Google Drive..."})
            try:
                uploader = DriveUploader()
                cf = uploader.get_or_create_folder(company_slug)
                rf = uploader.get_or_create_folder(f"{today}_{role_slug}", cf)
                if resume_ok:
                    resume_link = await loop.run_in_executor(
                        _executor, lambda: uploader.upload_file(resume_path, rf, resume_path.name)
                    )
                if cl_ok:
                    cl_link = await loop.run_in_executor(
                        _executor, lambda: uploader.upload_file(cl_path, rf, cl_path.name)
                    )
                yield _sse({"type": "gen_progress", "step": "drive_done", "message": "Uploaded to Google Drive"})
            except Exception as exc:
                yield _sse({"type": "gen_progress", "step": "drive_warn",
                            "message": f"Drive upload failed (non-fatal): {exc}"})

        resume_link = resume_link or str(resume_path.resolve())
        cl_link = cl_link or str(cl_path.resolve())

        # ── Record in DB + Applied sheet ─────────────────────────────────────
        yield _sse({"type": "gen_progress", "step": "record",
                    "message": "Recording in Applied sheet + DB..."})
        try:
            db = Database(DB_FILE)
            db.initialize()
            fingerprint = f"{inp.company.strip().lower()}||{inp.title.strip().lower()}"
            db.save_feedback(
                job_fingerprint=fingerprint,
                company=inp.company, title=inp.title, source=inp.source,
                screen_confidence=inp.confidence,
                resume_angle=result.get("decisions", {}).get("angle", ""),
                date_applied=today,
            )
            db.close()

            screened = ScreenedJob(
                title=inp.title, company=inp.company, location=inp.location,
                description=inp.description[:500] if inp.description else None,
                url=inp.url or "https://example.com", source=inp.source,
                h1b_sponsor_verified=inp.h1b_sponsor_verified,
                verdict=ScreeningVerdict.APPLY, confidence=inp.confidence,
                reasoning=inp.reasoning, suggested_angle=inp.suggested_angle,
            )
            sheets = SheetsClient()
            applied_ws = sheets.get_materials_sheet()
            materials_ops.add_job(
                applied_ws, screened,
                resume_link=resume_link, cover_letter_link=cl_link,
                angle_used=result.get("decisions", {}).get("angle", inp.suggested_angle),
                notes="Generated via web UI",
                status="Ready to Apply",
            )
            yield _sse({"type": "gen_progress", "step": "recorded",
                        "message": "Recorded in Applied sheet"})
        except Exception as exc:
            yield _sse({"type": "gen_progress", "step": "record_warn",
                        "message": f"Sheet/DB recording failed (non-fatal): {exc}"})

        # ── Done ─────────────────────────────────────────────────────────────
        yield _sse({
            "type": "gen_done",
            "resume_link": resume_link,
            "cl_link": cl_link,
            "interview_score": result.get("_interview_score"),
            "angle_used": result.get("decisions", {}).get("angle", inp.suggested_angle),
        })

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, reload=False)
