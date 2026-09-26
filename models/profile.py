"""Profile vault models — structured representation of the user's experience."""
from __future__ import annotations

from pydantic import BaseModel


class PersonalInfo(BaseModel):
    name: str
    email: str
    phone: str
    location: str
    visa: str
    linkedin: str = ""


class Education(BaseModel):
    school: str
    degree: str
    gpa: str = ""
    graduation: str


class Framing(BaseModel):
    title: str = ""
    bullets: list[str] = []


class Experience(BaseModel):
    company: str
    location: str
    period: str
    framings: dict[str, dict]  # e.g. {"security": {"title": "...", "bullets": [...]}}
    raw_context: str = ""


class ProjectSkills(BaseModel):
    """Skill tags by depth, using generation.skill_taxonomy keys."""
    core: list[str] = []
    supporting: list[str] = []
    touch: list[str] = []


class Project(BaseModel):
    name: str
    id: str = ""
    raw_context: str = ""
    framings: dict[str, dict] = {}  # e.g. {"healthcare": {"bullets": [...]}}
    skills: ProjectSkills = ProjectSkills()


class CatalogRef(BaseModel):
    """Pointer to a portfolio project spec (docs/projects/*.md)."""
    id: str
    name: str
    spec: str


class Certification(BaseModel):
    name: str
    issuer: str = ""
    status: str = ""
    expires: str = ""
    note: str = ""


class Profile(BaseModel):
    personal: PersonalInfo
    education: list[Education] = []
    experiences: list[Experience] = []
    projects: list[Project] = []
    portfolio_catalog: list[CatalogRef] = []
    certifications: list[Certification] = []
    training: list[str] = []
    skills: dict[str, list[str]] = {}
