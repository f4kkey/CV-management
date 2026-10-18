"""Typed final CV profile and reader-output structures; no inference."""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(StrictModel):
    page: int | None = None
    text: str | None = None
    line_ids: list[str] = Field(default_factory=list)


class PersonalInformation(StrictModel):
    full_name: str | None = None
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    location: str | None = None
    linkedin_url: str | None = None
    portfolio_url: str | None = None


class Skill(StrictModel):
    raw_name: str
    normalized_name: str | None = None


class WorkExperience(StrictModel):
    job_title: str | None = None
    company: str | None = None
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    is_current: bool = False
    description: list[str] = Field(default_factory=list)
    evidence: Evidence | None = None


class Education(StrictModel):
    institution: str | None = None
    degree: str | None = None
    field_of_study: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    grade: str | None = None
    evidence: Evidence | None = None


class Project(StrictModel):
    name: str | None = None
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)
    url: str | None = None


class Certification(StrictModel):
    name: str | None = None
    issuer: str | None = None
    issue_date: str | None = None
    expiration_date: str | None = None
    credential_id: str | None = None


class Language(StrictModel):
    name: str
    proficiency: str | None = None


class CvProfile(StrictModel):
    schema_version: str = "1.0"
    personal_information: PersonalInformation = Field(default_factory=PersonalInformation)
    summary: str | None = None
    skills: list[Skill] = Field(default_factory=list)
    work_experience: list[WorkExperience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    awards: list[str] = Field(default_factory=list)
    extraction_warnings: list[str] = Field(default_factory=list)


class SourceLine(StrictModel):
    line_id: str
    page: int
    text: str
    bbox: tuple[float, float, float, float] | None = None
    source_method: str
    confidence: float | None = None
    original_order: int
    reading_order: int
    column: int = 0
    section: str | None = None
    section_id: str | None = None


class SourcePage(StrictModel):
    page: int
    width: float
    height: float
    source_method: str
    lines: list[SourceLine] = Field(default_factory=list)


class SourceDocument(StrictModel):
    pages: list[SourcePage] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def prompt_text(self) -> str:
        sections = []
        for page in self.pages:
            lines = [
                f"[{line.line_id}] {line.text}"
                for line in sorted(page.lines, key=lambda item: item.reading_order)
            ]
            sections.append(f"--- PAGE {page.page} ({page.source_method}) ---\n" + "\n".join(lines))
        return "\n\n".join(sections)

