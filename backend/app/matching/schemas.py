from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobRecommendationCreate(StrictSchema):
    resume_id: UUID


class ResumeProfileVersionRef(StrictSchema):
    id: UUID
    version_no: int


class PublishedVersionRef(StrictSchema):
    id: UUID
    version_no: int


class MatchRunRead(StrictSchema):
    id: UUID
    owner_user_id: UUID
    resume_id: UUID
    resume_profile: ResumeProfileVersionRef
    graph_version: PublishedVersionRef
    catalog_version: PublishedVersionRef
    weight_version: str
    result_count: int
    high_count: int
    medium_count: int
    low_count: int
    created_at: datetime


class DomainSnapshotRead(StrictSchema):
    id: UUID
    code: str
    name: str


class JobRoleSummaryRead(StrictSchema):
    id: UUID
    canonical_name: str
    description: str | None
    domain: DomainSnapshotRead


class JobRoleSnapshotRead(JobRoleSummaryRead):
    definition_payload: dict[str, Any]


class CoverageDimensionRead(StrictSchema):
    score: float
    status: Literal["evaluated", "not_required"]
    matched_count: int
    total_count: int
    matched_importance: float
    total_importance: float


class EvidenceDimensionRead(StrictSchema):
    score: float
    status: Literal["evaluated", "no_matched_skill"]
    matched_count: int
    evidence_weighted_importance: float
    matched_importance: float


class ExperienceDimensionRead(StrictSchema):
    score: float
    status: Literal["not_required", "unknown", "unmet", "partial", "satisfied"]
    candidate_months: int | None
    recommended_months: int | None


class EducationDimensionRead(StrictSchema):
    score: float
    status: Literal["not_required", "unknown", "partial", "satisfied"]
    candidate_level: str | None
    minimum_level: str | None


class LGFDimensionRead(StrictSchema):
    status: Literal["ok", "degraded", "disabled"]
    score: float | None
    match_level: str | None
    error_code: str | None = None


class DimensionScoresRead(StrictSchema):
    required_skill_coverage: CoverageDimensionRead
    bonus_skill_coverage: CoverageDimensionRead
    skill_evidence_quality: EvidenceDimensionRead
    experience: ExperienceDimensionRead
    education: EducationDimensionRead
    lgf: LGFDimensionRead | None = None


class GapSummaryRead(StrictSchema):
    matched_required_count: int
    missing_required_count: int
    matched_bonus_count: int
    missing_bonus_count: int


class ResumeSkillSnapshotRead(StrictSchema):
    id: UUID
    raw_name: str
    mapping_method: Literal["canonical_exact", "alias_exact", "manual"]
    evidence_strength: Literal["mention", "project", "work"]
    evidence_factor: float
    evidence_quote: str | None


class MatchedCapabilityRead(StrictSchema):
    capability_id: UUID
    canonical_name: str
    requirement_type: Literal["required", "bonus"]
    importance: float
    resume_skill: ResumeSkillSnapshotRead


class MissingCapabilityRead(StrictSchema):
    capability_id: UUID
    canonical_name: str
    skill_type: str
    requirement_type: Literal["required", "bonus"]
    importance: float
    domain: DomainSnapshotRead


class MatchResultListItem(StrictSchema):
    job_role_id: UUID
    rank: int
    total_score: float
    match_level: Literal["high", "medium", "low"]
    job_role: JobRoleSummaryRead
    dimension_scores: DimensionScoresRead
    gap_summary: GapSummaryRead
    created_at: datetime


class MatchResultDetail(MatchResultListItem):
    job_role: JobRoleSnapshotRead
    matched_capabilities: list[MatchedCapabilityRead]
    missing_capabilities: list[MissingCapabilityRead]


class MatchResultPage(StrictSchema):
    items: list[MatchResultListItem]
    page: int
    page_size: int
    total: int


class MatchRunPage(StrictSchema):
    items: list[MatchRunRead]
    page: int
    page_size: int
    total: int


class RecommendationCreateData(StrictSchema):
    reused: bool
    run: MatchRunRead
    results: MatchResultPage


class RecommendationRunData(StrictSchema):
    run: MatchRunRead
    results: MatchResultPage


class RecommendationDetailData(StrictSchema):
    run: MatchRunRead
    result: MatchResultDetail
