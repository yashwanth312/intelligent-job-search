"""
============================================================
  GENERATE MATERIALS — Resume + Cover Letter Automation
============================================================
  Reads Apply jobs from Daily tab, generates tailored
  resume + cover letter for each, uploads to Drive,
  moves to Applied tab.
============================================================
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date
from pathlib import Path

from config import DB_FILE, YOUR_NAME
from db.database import Database
from generation.resume_engine import ResumeEngine
from generation.pdf_renderer import render_resume_pdf, render_cover_letter_pdf
from generation.drive_uploader import DriveUploader
from models.job import ScreenedJob, ScreeningVerdict
from sheets.client import SheetsClient
from sheets import daily as daily_ops, applied as applied_ops

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    return text.lower().replace(" ", "-").replace(",", "").replace(".", "")[:50]


def main():
    db = Database(DB_FILE)
    db.initialize()

    sheets = SheetsClient()
    daily_ws = sheets.get_daily_sheet()
    applied_ws = sheets.get_applied_sheet()

    apply_jobs = daily_ops.get_apply_jobs(daily_ws)
    if not apply_jobs:
        print("No jobs marked 'Apply' in Daily tab.")
        return

    print(f"\nGenerating materials for {len(apply_jobs)} jobs...\n")

    engine = ResumeEngine(profile_path="profile.yaml")
    uploader = DriveUploader()
    today = date.today().isoformat()

    for i, row in enumerate(apply_jobs, 1):
        company = row.get("Company", "")
        title = row.get("Job Title", "")
        location = row.get("Location", "")
        source = row.get("Source", "")
        confidence = row.get("Confidence", 3)
        reasoning = row.get("AI Reasoning", "")
        suggested_angle = row.get("Suggested Angle", "")
        apply_link = row.get("Apply Link", "")

        print(f"  [{i}/{len(apply_jobs)}] {company} — {title}")

        fingerprint = f"{company.strip().lower()}||{title.strip().lower()}"
        description = db.get_description_by_fingerprint(fingerprint) or ""

        result = engine.generate(
            company=company, title=title, location=location,
            description=description, source=source,
            screening_notes=f"Angle: {suggested_angle}. {reasoning}",
        )

        if not result:
            logger.error(f"  Failed to generate for {company} — {title}")
            continue

        company_slug = slugify(company)
        role_slug = slugify(title)
        output_dir = Path("output") / company_slug / f"{today}_{role_slug}"
        output_dir.mkdir(parents=True, exist_ok=True)

        resume_path = output_dir / f"{YOUR_NAME.replace(' ', '_')}_Resume.pdf"
        cl_path = output_dir / f"{YOUR_NAME.replace(' ', '_')}_Cover_Letter.pdf"

        render_resume_pdf(result, resume_path)
        render_cover_letter_pdf(
            result.get("cover_letter", ""), company, title, cl_path,
        )

        metadata_path = output_dir / "_metadata.json"
        metadata_path.write_text(json.dumps({
            "job": {"company": company, "title": title, "source": source, "confidence": confidence},
            "decisions": result.get("decisions", {}),
            "generated_at": today,
        }, indent=2))

        company_folder = uploader.get_or_create_folder(company_slug)
        role_folder = uploader.get_or_create_folder(f"{today}_{role_slug}", company_folder)

        resume_link = uploader.upload_file(resume_path, role_folder, resume_path.name)
        cl_link = uploader.upload_file(cl_path, role_folder, cl_path.name)

        screened = ScreenedJob(
            title=title, company=company, location=location,
            description="", url=apply_link, source=source,
            verdict=ScreeningVerdict.APPLY, confidence=int(confidence),
            reasoning=reasoning, suggested_angle=suggested_angle,
        )
        applied_ops.add_job(
            applied_ws, screened,
            resume_link=resume_link,
            cover_letter_link=cl_link,
            angle_used=result.get("decisions", {}).get("angle", suggested_angle),
        )

        db.save_feedback(
            job_fingerprint=fingerprint,
            company=company, title=title, source=source,
            screen_confidence=int(confidence),
            resume_angle=result.get("decisions", {}).get("angle", ""),
            date_applied=today,
        )

        print(f"    Done — Resume + Cover Letter generated and uploaded")

    db.close()
    print(f"\nDone! {len(apply_jobs)} materials generated. Check the Applied tab.\n")


if __name__ == "__main__":
    main()
