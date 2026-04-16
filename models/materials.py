"""Generated resume/cover letter metadata model."""
from __future__ import annotations

from pydantic import BaseModel


class ResumeDecisions(BaseModel):
    angle: str
    kvbits_framing: str = ""
    ti_framing: str = ""
    projects_included: list[str] = []
    projects_excluded: dict[str, str] = {}  # project_name -> reason
    skills_reordered: str = ""
    certs_highlighted: list[str] = []


class GeneratedMaterials(BaseModel):
    job_fingerprint: str
    company: str
    title: str
    resume_content: dict  # structured resume sections
    cover_letter: str
    decisions: ResumeDecisions
    resume_drive_url: str = ""
    cover_letter_drive_url: str = ""
