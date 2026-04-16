"""HTML template -> PDF conversion via weasyprint."""
from __future__ import annotations

import logging
from pathlib import Path

from weasyprint import HTML

from config import YOUR_NAME, YOUR_EMAIL, YOUR_PHONE

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "resume.html"


def render_resume_pdf(resume_data: dict, output_path: Path) -> bool:
    """Render resume dict to PDF. Returns True on success."""
    try:
        template = TEMPLATE_PATH.read_text()
        html = _fill_template(template, resume_data)
        HTML(string=html).write_pdf(str(output_path))
        logger.info(f"Resume PDF written to {output_path}")
        return True
    except Exception as e:
        logger.error(f"PDF rendering failed: {e}")
        return False


def render_cover_letter_pdf(cover_letter_text: str, company: str, title: str, output_path: Path) -> bool:
    """Render cover letter text to PDF."""
    try:
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family: 'Georgia', serif; margin: 60px; font-size: 11pt; line-height: 1.6; color: #333; }}
  .header {{ margin-bottom: 30px; }}
  .header h1 {{ font-size: 14pt; margin: 0; }}
  .header p {{ margin: 2px 0; font-size: 10pt; color: #555; }}
  .content {{ margin-top: 20px; }}
  .content p {{ margin-bottom: 12px; text-align: justify; }}
</style></head><body>
<div class="header">
  <h1>{YOUR_NAME}</h1>
  <p>{YOUR_EMAIL} | {YOUR_PHONE}</p>
</div>
<div class="content">
  {"".join(f"<p>{para.strip()}</p>" for para in cover_letter_text.split(chr(10)+chr(10)) if para.strip())}
</div>
</body></html>"""
        HTML(string=html).write_pdf(str(output_path))
        logger.info(f"Cover letter PDF written to {output_path}")
        return True
    except Exception as e:
        logger.error(f"Cover letter PDF failed: {e}")
        return False


def _fill_template(template: str, resume_data: dict) -> str:
    """Fill the HTML template with resume data."""
    resume = resume_data.get("resume", {})

    exp_html = ""
    for exp in resume.get("experience", []):
        bullets = "".join(f"<li>{b}</li>" for b in exp.get("bullets", []))
        exp_html += f"""
        <div class="experience">
          <div class="job-header">
            <span class="job-title">{exp.get('title', '')} | {exp.get('company', '')}, {exp.get('location', '')}</span>
            <span class="dates">{exp.get('period', '')}</span>
          </div>
          <ul>{bullets}</ul>
        </div>"""

    proj_html = ""
    for proj in resume.get("projects", []):
        bullets = "".join(f"<li>{b}</li>" for b in proj.get("bullets", []))
        proj_html += f"""
        <div class="project">
          <strong>{proj.get('name', '')}</strong>
          <ul>{bullets}</ul>
        </div>"""

    skills_html = ""
    for category, items in resume.get("skills", {}).items():
        skills_html += f"<li><strong>{category}:</strong> {', '.join(items)}</li>"

    certs = resume.get("certifications", [])
    certs_html = "".join(f"<li>{c}</li>" for c in certs)

    return (
        template
        .replace("{{name}}", YOUR_NAME)
        .replace("{{email}}", YOUR_EMAIL)
        .replace("{{phone}}", YOUR_PHONE)
        .replace("{{summary}}", resume.get("summary", ""))
        .replace("{{experience}}", exp_html)
        .replace("{{projects}}", proj_html)
        .replace("{{skills}}", skills_html)
        .replace("{{certifications}}", certs_html)
    )
