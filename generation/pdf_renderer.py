"""HTML template -> PDF conversion via weasyprint.

WeasyPrint requires GTK3 runtime (libgobject-2.0-0 etc.) on Windows.
If those native libraries aren't installed, we lazy-import at call time
and fall back to writing an .html file alongside, which you can print
to PDF from a browser (Ctrl+P -> Save as PDF).

Install GTK3 on Windows:
  1. Download GTK3-Runtime installer:
       https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases
  2. Run the installer and restart your terminal.
  3. Verify: `python -c "from weasyprint import HTML"` runs without error.
"""
from __future__ import annotations

import html as html_lib
import logging
import re
from datetime import date
from pathlib import Path

from config import (
    YOUR_NAME,
    YOUR_EMAIL,
    YOUR_PHONE,
    YOUR_LOCATION_FALLBACK,
    YOUR_LINKEDIN,
    YOUR_GITHUB,
)

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "resume.html"

# Empirical char-count budget for the contact line so it fits on one row at
# 9.5pt Calibri across a 7.5"-wide content area. If the full line exceeds this,
# drop GitHub first, then email — never drop name/phone/location/linkedin.
_CONTACT_LINE_MAX_CHARS = 110

_WEASYPRINT_INSTALL_HINT = (
    "WeasyPrint can't load its native libraries (GTK3 runtime). "
    "Install the GTK3 runtime for Windows: "
    "https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases "
    "then restart your terminal. Falling back to saving .html — "
    "open it in a browser and use Ctrl+P -> 'Save as PDF'."
)


def _try_import_weasyprint():
    try:
        from weasyprint import HTML
        return HTML
    except OSError as e:
        logger.error(f"WeasyPrint native libraries not available: {e}")
        logger.error(_WEASYPRINT_INSTALL_HINT)
        return None


def _write_html_fallback(html: str, pdf_path: Path) -> Path:
    html_path = pdf_path.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")
    logger.warning(f"Wrote HTML fallback to {html_path} (open + Ctrl+P to save PDF)")
    return html_path


def _escape_with_bold(text: str) -> str:
    """HTML-escape text, then convert **foo** markers to <strong>foo</strong>."""
    escaped = html_lib.escape(text or "")
    return re.sub(r'\*\*([^*]+?)\*\*', r'<strong>\1</strong>', escaped)


def _build_contact_line(location: str) -> str:
    """Build the header contact line. Drops GitHub then email if too long."""
    loc = location or YOUR_LOCATION_FALLBACK
    full = f"{loc} | {YOUR_PHONE} | {YOUR_LINKEDIN} | {YOUR_EMAIL} | {YOUR_GITHUB}"
    if len(full) <= _CONTACT_LINE_MAX_CHARS:
        return html_lib.escape(full)
    no_github = f"{loc} | {YOUR_PHONE} | {YOUR_LINKEDIN} | {YOUR_EMAIL}"
    if len(no_github) <= _CONTACT_LINE_MAX_CHARS:
        return html_lib.escape(no_github)
    no_email = f"{loc} | {YOUR_PHONE} | {YOUR_LINKEDIN}"
    return html_lib.escape(no_email)


def render_resume_pdf(resume_data: dict, output_path: Path) -> bool:
    """Render resume dict to PDF. Returns True on PDF success, False on any failure
    (HTML fallback is still written when WeasyPrint is unavailable)."""
    try:
        template = TEMPLATE_PATH.read_text()
        html = _fill_template(template, resume_data)
    except Exception as e:
        logger.error(f"Resume template load/fill failed: {e}")
        return False

    HTML = _try_import_weasyprint()
    if HTML is None:
        _write_html_fallback(html, output_path)
        return False

    try:
        HTML(string=html).write_pdf(str(output_path))
        logger.info(f"Resume PDF written to {output_path}")
        return True
    except Exception as e:
        logger.error(f"PDF rendering failed: {e}")
        _write_html_fallback(html, output_path)
        return False


def render_cover_letter_pdf(
    cover_letter_text: str,
    company: str,
    title: str,
    output_path: Path,
    location: str = "",
    today: date | None = None,
) -> bool:
    """Render cover letter text to PDF with date + recipient block."""
    today = today or date.today()
    date_str = today.strftime("%B %d, %Y")
    company_loc = location or "Remote"
    contact_line = _build_contact_line(location)

    body_paragraphs = [
        f"<p>{html_lib.escape(p.strip())}</p>"
        for p in cover_letter_text.split("\n\n")
        if p.strip()
    ]
    body_html = "\n  ".join(body_paragraphs)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  @page {{ margin: 0.75in; size: letter; }}
  body {{
    font-family: 'Calibri', 'Helvetica Neue', Arial, sans-serif;
    font-size: 11pt;
    color: #222;
    margin: 0;
    line-height: 1.5;
  }}
  h1 {{
    font-size: 20pt;
    margin: 0 0 4px 0;
    color: #1F3864;
    font-weight: 700;
    letter-spacing: 0.3px;
    text-align: center;
  }}
  .contact {{ font-size: 9.5pt; color: #333; margin-bottom: 8px; text-align: center; }}
  .header-rule {{
    border-bottom: 1px solid #1F3864;
    margin-bottom: 22px;
  }}
  .date {{ margin: 0 0 18px 0; }}
  .recipient {{ margin: 0 0 18px 0; }}
  .recipient div {{ margin: 0; }}
  .body p {{ margin: 0 0 12px 0; text-align: justify; }}
</style></head><body>
<h1>{html_lib.escape(YOUR_NAME)}</h1>
<div class="contact">{contact_line}</div>
<div class="header-rule"></div>

<div class="date">{html_lib.escape(date_str)}</div>

<div class="recipient">
  <div>Hiring Manager</div>
  <div>{html_lib.escape(company)}</div>
  <div>{html_lib.escape(company_loc)}</div>
</div>

<div class="body">
  {body_html}
</div>
</body></html>"""

    HTML = _try_import_weasyprint()
    if HTML is None:
        _write_html_fallback(html, output_path)
        return False

    try:
        HTML(string=html).write_pdf(str(output_path))
        logger.info(f"Cover letter PDF written to {output_path}")
        return True
    except Exception as e:
        logger.error(f"Cover letter PDF failed: {e}")
        _write_html_fallback(html, output_path)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Resume template filler
# ─────────────────────────────────────────────────────────────────────────────

def _fill_template(template: str, resume_data: dict) -> str:
    resume = resume_data.get("resume", {})
    personal = resume.get("personal", {}) or {}
    location = personal.get("location") or YOUR_LOCATION_FALLBACK

    contact_line = _build_contact_line(location)
    summary = _escape_with_bold(resume.get("summary", ""))
    experience_html = _render_experience(resume.get("experience", []))
    education_html = _render_education(resume.get("education", []))
    skills_html = _render_skills(resume.get("skills", {}))
    certifications_html = _render_certifications(resume.get("certifications", []))
    projects_html = _render_projects(resume.get("projects", []))
    publications_html = _render_publications(resume.get("publications", []))

    return (
        template
        .replace("{{name}}", html_lib.escape(YOUR_NAME))
        .replace("{{contact_line}}", contact_line)
        .replace("{{summary}}", summary)
        .replace("{{experience}}", experience_html)
        .replace("{{education}}", education_html)
        .replace("{{skills}}", skills_html)
        .replace("{{certifications}}", certifications_html)
        .replace("{{projects}}", projects_html)
        .replace("{{publications_section}}", publications_html)
    )


def _render_experience(experiences: list) -> str:
    out = []
    for exp in experiences:
        bullets = "".join(f"<li>{_escape_with_bold(b)}</li>" for b in exp.get("bullets", []))
        title = html_lib.escape(exp.get("title", ""))
        company = html_lib.escape(exp.get("company", ""))
        loc = html_lib.escape(exp.get("location", ""))
        period = html_lib.escape(exp.get("period", ""))
        title_line = f"{title} | {company}" + (f", {loc}" if loc else "")
        out.append(f"""
        <div class="experience">
          <div class="job-header">
            <span class="job-title">{title_line}</span>
            <span class="dates">{period}</span>
          </div>
          <ul>{bullets}</ul>
        </div>""")
    return "".join(out)


def _render_education(education: list) -> str:
    out = []
    for edu in education:
        school = html_lib.escape(edu.get("school", ""))
        degree = html_lib.escape(edu.get("degree", ""))
        gpa = edu.get("gpa", "")
        graduation = html_lib.escape(edu.get("graduation", ""))
        left_parts = [school, degree]
        if gpa:
            left_parts.append(f"GPA {html_lib.escape(str(gpa))}")
        left = " — ".join(p for p in left_parts if p)
        out.append(f"""
        <div class="edu-row">
          <span class="edu-left">{left}</span>
          <span class="edu-date">{graduation}</span>
        </div>""")
    return "".join(out)


def _render_skills(skills: dict) -> str:
    rows = []
    for category, items in skills.items():
        cat = html_lib.escape(str(category))
        items_html = ", ".join(_escape_with_bold(str(i)) for i in items)
        rows.append(f"<tr><td class='cat'>{cat}:</td><td>{items_html}</td></tr>")
    return "".join(rows)


def _render_certifications(certifications: list) -> str:
    rows = []
    for cert in certifications:
        name = html_lib.escape(cert.get("name", ""))
        issuer = html_lib.escape(cert.get("issuer", ""))
        cred_id = html_lib.escape(cert.get("credential_id", "") or "")
        issued = html_lib.escape(cert.get("issued", "") or "")
        expires = html_lib.escape(cert.get("expires", "") or "")
        rows.append(
            f"<tr>"
            f"<td class='cert-name'>{name}</td>"
            f"<td>{issuer}</td>"
            f"<td>{cred_id}</td>"
            f"<td>{issued}</td>"
            f"<td>{expires}</td>"
            f"</tr>"
        )
    return "".join(rows)


def _render_projects(projects: list) -> str:
    out = []
    for proj in projects:
        bullets = "".join(f"<li>{_escape_with_bold(b)}</li>" for b in proj.get("bullets", []))
        name = html_lib.escape(proj.get("name", ""))
        out.append(f"""
        <div class="project">
          <div class="project-name">{name}</div>
          <ul>{bullets}</ul>
        </div>""")
    return "".join(out)


def _render_publications(publications: list) -> str:
    if not publications:
        return ""
    items = []
    for pub in publications:
        title = html_lib.escape(pub.get("title", ""))
        venue = html_lib.escape(pub.get("venue", "") or "")
        desc = html_lib.escape(pub.get("description", "") or "")
        venue_html = f' <span class="pub-venue">— {venue}</span>' if venue else ""
        items.append(
            f'<div class="pub"><span class="pub-title">{title}</span>{venue_html}<div>{desc}</div></div>'
        )
    return "<h2>Research Publications</h2>\n" + "\n".join(items)
