from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.discovery.mining import normalize_skill_label

Confidence = Annotated[float, Field(ge=0, le=1)]
Importance = Annotated[float, Field(gt=0, le=1)]
RequirementType = Literal["required", "bonus"]
EducationLevel = Literal[
    "high_school",
    "associate",
    "bachelor",
    "master",
    "doctor",
    "other",
    "unknown",
]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JDResponsibility(StrictSchema):
    text: Annotated[str, Field(min_length=1, max_length=500)]
    evidence_quote: Annotated[str, Field(min_length=1, max_length=1000)]


class JDExtractedSkill(StrictSchema):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    requirement_type: RequirementType
    importance: Importance
    evidence_quote: Annotated[str, Field(min_length=1, max_length=1000)]
    confidence: Confidence


class RecruitmentJDParseResponse(StrictSchema):
    job_title: Annotated[str, Field(min_length=1, max_length=200)]
    summary: Annotated[str, Field(max_length=1000)] | None
    responsibilities: Annotated[list[JDResponsibility], Field(max_length=30)]
    minimum_education_level: EducationLevel | None
    recommended_experience_months: Annotated[int, Field(ge=0, le=600)] | None
    skills: Annotated[list[JDExtractedSkill], Field(max_length=100)]


class RequirementReplaceItem(StrictSchema):
    capability_id: UUID
    requirement_type: RequirementType
    importance: Importance


class UnmappedSkillReplaceItem(StrictSchema):
    raw_name: Annotated[str, Field(min_length=1, max_length=200)]
    requirement_type: RequirementType


class RequirementsReplaceRequest(StrictSchema):
    job_title: Annotated[str, Field(min_length=1, max_length=200)]
    summary: Annotated[str, Field(max_length=1000)] | None
    responsibilities: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=500)]],
        Field(max_length=30),
    ]
    minimum_education_level: EducationLevel | None
    recommended_experience_months: Annotated[int, Field(ge=0, le=600)] | None
    requirements: Annotated[list[RequirementReplaceItem], Field(max_length=100)]
    unmapped_skills: Annotated[list[UnmappedSkillReplaceItem], Field(max_length=100)]

    @model_validator(mode="after")
    def validate_unique_requirements(self):
        capability_ids = [item.capability_id for item in self.requirements]
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("duplicate capability_id")

        normalized_names = [
            normalize_skill_label(item.raw_name) for item in self.unmapped_skills
        ]
        if not all(normalized_names) or len(normalized_names) != len(
            set(normalized_names)
        ):
            raise ValueError("duplicate or empty unmapped skill")
        return self


class RecruitmentProjectCreateRequest(StrictSchema):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(max_length=5000)] | None = None


class RecruitmentProjectResponse(StrictSchema):
    id: UUID
    owner_user_id: UUID
    title: str
    description: str | None
    jd_source_type: str | None
    jd_file_id: UUID | None
    jd_parse_status: str
    jd_draft_payload: dict
    confirmed_requirement_summary: dict
    confirmed_requirement_sha256: str | None
    requirements_revision: int
    latest_jd_run_id: UUID | None
    candidate_counts: dict[str, int]
    latest_processing_run: dict | None
    latest_match_run: dict | None
    created_at: datetime
    updated_at: datetime


class RecruitmentJDSubmitResponse(StrictSchema):
    project_id: UUID
    run_id: UUID
    run_url: str


class RequirementsConfirmResponse(StrictSchema):
    project_id: UUID
    requirements_revision: int
    requirements_sha256: str
    reused: bool
    confirmed_at: datetime
    snapshot: dict


class RecruitmentCandidateCreatedResponse(StrictSchema):
    id: UUID
    display_name: str
    parse_status: Literal["uploaded"]
    file_id: UUID


class RecruitmentCandidateUploadResponse(StrictSchema):
    project_id: UUID
    run_id: UUID
    run_url: str
    candidates: list[RecruitmentCandidateCreatedResponse]
