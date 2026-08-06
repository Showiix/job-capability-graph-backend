from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Month = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
Confidence = Annotated[float, Field(ge=0, le=1)]
ShortText = Annotated[str, Field(max_length=200)]
EvidenceQuote = Annotated[str, Field(min_length=1, max_length=1000)]
EducationLevel = Literal[
    "high_school",
    "associate",
    "bachelor",
    "master",
    "doctor",
    "other",
    "unknown",
]
Proficiency = Literal["beginner", "intermediate", "advanced"]
EvidenceStrength = Literal["mention", "project", "work"]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DateRange(StrictSchema):
    start_month: Month | None
    end_month: Month | None
    is_current: bool

    @model_validator(mode="after")
    def validate_dates(self):
        if self.is_current and self.end_month is not None:
            raise ValueError("current item cannot have end_month")
        if self.start_month and self.end_month and self.end_month < self.start_month:
            raise ValueError("end_month cannot precede start_month")
        return self


class DatedEvidence(DateRange):
    evidence_quote: EvidenceQuote
    confidence: Confidence


class EducationItem(DatedEvidence):
    school_name: Annotated[str, Field(min_length=1, max_length=200)]
    major: ShortText | None
    education_level: EducationLevel


class ExperienceItem(DatedEvidence):
    company_name: Annotated[str, Field(min_length=1, max_length=200)]
    job_title: ShortText | None
    responsibilities: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=500)]],
        Field(max_length=10),
    ]


class ProjectItem(DatedEvidence):
    project_name: Annotated[str, Field(min_length=1, max_length=200)]
    role: ShortText | None
    description: Annotated[str, Field(max_length=1000)] | None


class SkillItem(StrictSchema):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    proficiency: Proficiency | None
    explicit_experience_months: Annotated[int, Field(ge=0)] | None
    evidence_strength: EvidenceStrength
    evidence_quote: EvidenceQuote
    confidence: Confidence


class ResumeParseResponse(StrictSchema):
    schema_version: Literal["resume_parse_v1"]
    document_language: Annotated[str, Field(min_length=1, max_length=20)]
    summary: Annotated[str, Field(max_length=1000)] | None
    educations: Annotated[list[EducationItem], Field(max_length=10)]
    experiences: Annotated[list[ExperienceItem], Field(max_length=30)]
    projects: Annotated[list[ProjectItem], Field(max_length=30)]
    skills: Annotated[list[SkillItem], Field(max_length=100)]


class ManualEducationInput(DateRange):
    school_name: Annotated[str, Field(min_length=1, max_length=200)]
    major: ShortText | None
    education_level: EducationLevel
    evidence_quote: EvidenceQuote | None


class ManualExperienceInput(DateRange):
    company_name: Annotated[str, Field(min_length=1, max_length=200)]
    job_title: ShortText | None
    responsibilities: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=500)]],
        Field(max_length=10),
    ]
    evidence_quote: EvidenceQuote | None


class ManualProjectInput(DateRange):
    project_name: Annotated[str, Field(min_length=1, max_length=200)]
    role: ShortText | None
    description: Annotated[str, Field(max_length=1000)] | None
    evidence_quote: EvidenceQuote | None


class ManualSkillInput(StrictSchema):
    raw_name: Annotated[str, Field(min_length=1, max_length=200)]
    capability_id: UUID | None
    proficiency: Proficiency | None
    explicit_experience_months: Annotated[int, Field(ge=0)] | None
    evidence_strength: EvidenceStrength
    evidence_quote: EvidenceQuote | None


class ManualProfileReplaceRequest(StrictSchema):
    document_language: Annotated[str, Field(min_length=1, max_length=20)]
    summary: Annotated[str, Field(max_length=1000)] | None
    educations: Annotated[list[ManualEducationInput], Field(max_length=10)]
    experiences: Annotated[list[ManualExperienceInput], Field(max_length=30)]
    projects: Annotated[list[ManualProjectInput], Field(max_length=30)]
    skills: Annotated[list[ManualSkillInput], Field(max_length=100)]


class ResumeCreatedResponse(StrictSchema):
    resource_id: UUID
    run_id: UUID
    status: Literal["processing"]
    poll_url: str


class ResumeFileLinks(StrictSchema):
    id: UUID
    metadata_url: str
    content_url: str
    download_url: str


class ResumeResponse(StrictSchema):
    id: UUID
    display_name: str
    file: ResumeFileLinks
    parse_status: Literal["uploaded", "processing", "ready", "failed", "archived"]
    latest_run_id: UUID | None
    latest_profile_version: int | None
    confirmed_profile_version: int | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class ResumeProfileSummaryResponse(StrictSchema):
    id: UUID
    resume_id: UUID
    version_no: int
    base_profile_version: int | None
    profile_source: Literal["extracted", "manual_revision"]
    status: Literal["candidate", "draft", "confirmed", "superseded"]
    extraction_version: str
    highest_education_level: str | None
    total_experience_months: int | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ResumeSkillResponse(StrictSchema):
    id: UUID
    raw_name: str
    normalized_name: str
    capability_id: UUID | None
    capability_name: str | None
    proficiency: Proficiency | None
    explicit_experience_months: int | None
    evidence_strength: EvidenceStrength
    evidence_quote: str | None
    evidence_start: int | None
    evidence_end: int | None
    mapping_method: Literal["canonical_exact", "alias_exact", "manual", "unmapped"]
    mapping_status: Literal["mapped", "unmapped"]
    source: Literal["llm", "manual"]
    confidence: float
    user_confirmed: bool


class ResumeProfileResponse(ResumeProfileSummaryResponse):
    text_extraction_method: Literal["pdf_text", "docx"]
    profile: dict[str, Any]
    skills: list[ResumeSkillResponse]


class ExtractedTextResponse(StrictSchema):
    resume_id: UUID
    profile_id: UUID
    profile_version: int
    text_extraction_method: Literal["pdf_text", "docx"]
    extracted_text: str
