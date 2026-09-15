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
from generation.ats import BULLET_CHAR, normalize_skill_items, sanitize_text

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "resume.html"

# Empirical char-count budget for the contact line so it fits on one row at
# 9.5pt Calibri across a 7.5"-wide content area. Above this we wrap to two lines
# (location/phone/email on top, linkedin/github on bottom) so GitHub is always
# present — engineering applications need it.
_CONTACT_LINE_MAX_CHARS = 120

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


def _escape_with_bold(text: str, *, preserve_ampersand: bool = False) -> str:
    """ATS-sanitize text, HTML-escape it, then convert **foo** to <strong>foo</strong>.

    Sanitization must run before escaping -- afterwards the text contains
    `&amp;` entities that the ampersand rule would mangle.
    """
    escaped = html_lib.escape(sanitize_text(text, preserve_ampersand=preserve_ampersand))
    return re.sub(r'\*\*([^*]+?)\*\*', r'<strong>\1</strong>', escaped)


def _esc(text: str, *, preserve_ampersand: bool = False) -> str:
    """Sanitize + escape a plain field carrying no bold markers."""
    return html_lib.escape(sanitize_text(text, preserve_ampersand=preserve_ampersand))


def _render_bullets(bullets: list) -> str:
    """Render bullets as hanging-indent paragraphs, NOT <ul><li>.

    WeasyPrint emits `<li>` markers as separately-positioned text runs that the
    PDF content stream flushes at the end of the page, detached from their text.
    All 619 surveyed resumes carried such orphaned glyph runs, and in 602 of
    them the run landed inside the Skills section and split it in half -- the
    likeliest cause of Workday failing to populate skills. Carrying the marker
    as inline text keeps every bullet contiguous in reading order; `pdf_tags`
    does not fix this (measured).
    """
    return "".join(
        f'<p class="bullet">{BULLET_CHAR} {_escape_with_bold(b)}</p>'
        for b in bullets or []
    )


def _build_contact_line(location: str) -> str:
    """Build the header contact line. Single line if it fits; otherwise wraps to
    two lines so GitHub is always present (engineering applications need it)."""
    loc = sanitize_text(location) or YOUR_LOCATION_FALLBACK
    full = f"{loc} | {YOUR_PHONE} | {YOUR_LINKEDIN} | {YOUR_EMAIL} | {YOUR_GITHUB}"
    if len(full) <= _CONTACT_LINE_MAX_CHARS:
        return _esc(full)
    line1 = " | ".join(p for p in (loc, YOUR_PHONE, YOUR_EMAIL) if p)
    line2 = " | ".join(p for p in (YOUR_LINKEDIN, YOUR_GITHUB) if p)
    return _esc(line1) + "<br>" + _esc(line2)


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
        f"<p>{_esc(p.strip(), preserve_ampersand=True)}</p>"
        for p in cover_letter_text.split("\n\n")
        if p.strip()
    ]
    body_html = "\n  ".join(body_paragraphs)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>{_esc(YOUR_NAME, preserve_ampersand=True)} - Cover Letter - {_esc(company, preserve_ampersand=True)}</title>
<meta name="author" content="{_esc(YOUR_NAME, preserve_ampersand=True)}">
<meta name="description" content="Cover letter for {_esc(title, preserve_ampersand=True)}">
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
<h1>{_esc(YOUR_NAME, preserve_ampersand=True)}</h1>
<div class="contact">{contact_line}</div>
<div class="header-rule"></div>

<div class="date">{_esc(date_str)}</div>

<div class="recipient">
  <div>Hiring Manager</div>
  <div>{_esc(company, preserve_ampersand=True)}</div>
  <div>{_esc(company_loc)}</div>
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
        .replace("{{name}}", _esc(YOUR_NAME, preserve_ampersand=True))
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
        bullets = _render_bullets(exp.get("bullets", []))
        # Titles and company names are locked identity strings cross-checked
        # against LinkedIn, so their ampersands survive verbatim.
        title = _esc(exp.get("title", ""), preserve_ampersand=True)
        company = _esc(exp.get("company", ""), preserve_ampersand=True)
        loc = _esc(exp.get("location", ""))
        period = _esc(exp.get("period", ""))
        title_line = f"{title} | {company}" + (f", {loc}" if loc else "")
        out.append(f"""
        <div class="experience">
          <div class="job-header">
            <span class="job-title">{title_line}</span>
            <span class="dates">{period}</span>
          </div>
          {bullets}
        </div>""")
    return "".join(out)


def _render_education(education: list) -> str:
    out = []
    for edu in education:
        school = _esc(edu.get("school", ""), preserve_ampersand=True)
        degree = _esc(edu.get("degree", ""), preserve_ampersand=True)
        gpa = edu.get("gpa", "")
        graduation = _esc(edu.get("graduation", ""))
        left_parts = [school, degree]
        if gpa:
            # Keep "GPA 4.0" on one line — a line break between the label and
            # the value makes education parsers miss the GPA entirely.
            left_parts.append(f'<span class="nowrap">GPA {_esc(str(gpa))}</span>')
        # ASCII " - " rather than an em dash: education field extractors key off
        # the separator, and a hyphen is the one they all agree on.
        left = " - ".join(p for p in left_parts if p)
        out.append(f"""
        <div class="edu-row">
          <span class="edu-left">{left}</span>
          <span class="edu-date">{graduation}</span>
        </div>""")
    return "".join(out)


def _render_skills(skills: dict) -> str:
    """Render skills as plain "Category: a, b, c" text rows (no tables — ATS
    parsers routinely mangle multi-column tables and drop keywords).

    Items are normalized first so that every comma-delimited token stands alone
    as a matchable skill name. Workday splits this line on commas and matches
    each token against its taxonomy, so an un-normalized `AWS (EC2, S3)` yields
    the unmatchable fragments `AWS (EC2` and `S3)` and silently costs the whole
    category. See generation.ats.normalize_skill_items.
    """
    rows = []
    for category, items in skills.items():
        cat = _esc(str(category))
        items_html = ", ".join(
            _escape_with_bold(item) for item in normalize_skill_items(items)
        )
        rows.append(
            f'<p class="skill-row"><span class="skill-cat">{cat}:</span> {items_html}</p>'
        )
    return "".join(rows)


def _render_certifications(certifications: list) -> str:
    """Render certs as compact single-line text rows (no tables, no credential
    IDs). Credential IDs are long UUIDs that clutter the page and are never
    typed by a recruiter to verify — certs are looked up by name at the issuer.
    Format: "Name — Issuer (YYYY)"."""
    rows = []
    for cert in certifications:
        name = _esc(cert.get("name", ""), preserve_ampersand=True)
        issuer = _esc(cert.get("issuer", "") or "", preserve_ampersand=True)
        issued = str(cert.get("issued", "") or "")
        year = issued[-4:] if len(issued) >= 4 and issued[-4:].isdigit() else issued
        line = f'<span class="cert-name">{name}</span>'
        if issuer:
            line += f" - {issuer}"
        if year:
            line += f" ({_esc(year)})"
        rows.append(f'<div class="cert-row">{line}</div>')
    return "".join(rows)


def _render_projects(projects: list) -> str:
    out = []
    for proj in projects:
        bullets = _render_bullets(proj.get("bullets", []))
        # Canonical project names are locked strings — keep their ampersands.
        name = _esc(proj.get("name", ""), preserve_ampersand=True)
        out.append(f"""
        <div class="project">
          <div class="project-name">{name}</div>
          {bullets}
        </div>""")
    return "".join(out)


def _render_publications(publications: list) -> str:
    if not publications:
        return ""
    items = []
    for pub in publications:
        title = _esc(pub.get("title", ""), preserve_ampersand=True)
        venue = _esc(pub.get("venue", "") or "", preserve_ampersand=True)
        desc = _esc(pub.get("description", "") or "")
        venue_html = f' <span class="pub-venue">- {venue}</span>' if venue else ""
        items.append(
            f'<div class="pub"><span class="pub-title">{title}</span>{venue_html}<div>{desc}</div></div>'
        )
    return "<h2>Research Publications</h2>\n" + "\n".join(items)
