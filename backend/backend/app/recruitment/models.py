from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base, CreatedAtMixin


class RecruitmentProject(CreatedAtMixin, Base):
    __tablename__ = "recruitment_projects"
    __table_args__ = (
        CheckConstraint(
            "jd_source_type IS NULL OR jd_source_type IN ('text','file')",
            name="jd_source_type",
        ),
        CheckConstraint(
            "jd_parse_status IN ('empty','processing','ready','failed')",
            name="jd_parse_status",
        ),
        CheckConstraint("requirements_revision >= 0", name="requirements_revision"),
        CheckConstraint(
            "jsonb_typeof(jd_draft_payload) = 'object'",
            name="jd_draft_payload_object",
        ),
        CheckConstraint(
            "jsonb_typeof(confirmed_requirement_snapshot) = 'object'",
            name="confirmed_requirement_snapshot_object",
        ),
        CheckConstraint(
            "(requirements_revision = 0 "
            "AND confirmed_requirement_sha256 IS NULL "
            "AND confirmed_requirement_snapshot = '{}'::jsonb) OR "
            "(requirements_revision >= 1 "
            "AND confirmed_requirement_sha256 IS NOT NULL "
            "AND confirmed_requirement_snapshot <> '{}'::jsonb)",
            name="confirmed_requirement_revision",
        ),
        CheckConstraint(
            "(jd_source_type IS NULL AND jd_file_id IS NULL) OR "
            "(jd_source_type = 'text' AND jd_file_id IS NULL) OR "
            "(jd_source_type = 'file' AND jd_file_id IS NOT NULL)",
            name="jd_source_file",
        ),
        Index(
            "ix_recruitment_projects_owner_created",
            "owner_user_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_recruitment_projects_status_updated",
            "jd_parse_status",
            text("updated_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    jd_source_type: Mapped[str | None] = mapped_column(String(20))
    jd_file_id: Mapped[UUID | None] = mapped_column(ForeignKey("stored_files.id"))
    jd_source_text: Mapped[str | None] = mapped_column(Text)
    jd_parse_status: Mapped[str] = mapped_column(
        String(20), default="empty", server_default="empty", nullable=False
    )
    jd_draft_payload: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    confirmed_requirement_snapshot: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    confirmed_requirement_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    requirements_revision: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    latest_jd_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("processing_runs.id")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RecruitmentCandidate(CreatedAtMixin, Base):
    __tablename__ = "recruitment_candidates"
    __table_args__ = (
        UniqueConstraint("file_id", name="uq_recruitment_candidates_file_id"),
        CheckConstraint(
            "parse_status IN ('uploaded','processing','ready','failed')",
            name="parse_status",
        ),
        Index(
            "ix_recruitment_candidates_project_status_created",
            "project_id",
            "parse_status",
            text("created_at DESC"),
        ),
        Index(
            "ix_recruitment_candidates_project_name",
            "project_id",
            "display_name",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("recruitment_projects.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[UUID] = mapped_column(ForeignKey("stored_files.id"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    parse_status: Mapped[str] = mapped_column(
        String(20), default="uploaded", server_default="uploaded", nullable=False
    )
    latest_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("processing_runs.id"))
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CandidateProfile(CreatedAtMixin, Base):
    __tablename__ = "candidate_profiles"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_candidate_profiles_candidate_id"),
        CheckConstraint(
            "text_extraction_method IN ('pdf_text','docx')",
            name="text_extraction_method",
        ),
        CheckConstraint(
            "total_experience_months IS NULL OR total_experience_months >= 0",
            name="experience_months",
        ),
        CheckConstraint(
            "jsonb_typeof(structured_payload) = 'object'",
            name="structured_payload_object",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("recruitment_candidates.id", ondelete="CASCADE"), nullable=False
    )
    extraction_version: Mapped[str] = mapped_column(String(80), nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    text_extraction_method: Mapped[str] = mapped_column(String(20), nullable=False)
    highest_education_level: Mapped[str | None] = mapped_column(String(30))
    total_experience_months: Mapped[int | None] = mapped_column(Integer)
    structured_payload: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    created_by_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("processing_runs.id"), nullable=False
    )


class CandidateSkill(CreatedAtMixin, Base):
    __tablename__ = "candidate_skills"
    __table_args__ = (
        UniqueConstraint(
            "profile_id", "normalized_name", name="uq_candidate_skills_name"
        ),
        CheckConstraint(
            "proficiency IS NULL OR "
            "proficiency IN ('beginner','intermediate','advanced')",
            name="proficiency",
        ),
        CheckConstraint(
            "explicit_experience_months IS NULL OR explicit_experience_months >= 0",
            name="experience_months",
        ),
        CheckConstraint(
            "evidence_strength IN ('mention','project','work')",
            name="evidence_strength",
        ),
        CheckConstraint(
            "mapping_method IN ('canonical_exact','alias_exact','unmapped')",
            name="mapping_method",
        ),
        CheckConstraint(
            "mapping_status IN ('mapped','unmapped')", name="mapping_status"
        ),
        CheckConstraint(
            "(mapping_status = 'mapped') = (capability_id IS NOT NULL)",
            name="mapping_target",
        ),
        CheckConstraint(
            "(mapping_status = 'mapped' AND mapping_method IN "
            "('canonical_exact','alias_exact')) OR "
            "(mapping_status = 'unmapped' AND mapping_method = 'unmapped')",
            name="mapping_combination",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence"),
        CheckConstraint(
            "evidence_start >= 0 AND evidence_end > evidence_start",
            name="evidence_offsets",
        ),
        Index("ix_candidate_skills_mapping", "profile_id", "mapping_status"),
        Index(
            "ix_candidate_skills_capability",
            "capability_id",
            postgresql_where=text("capability_id IS NOT NULL"),
        ),
        Index(
            "uq_candidate_skills_profile_capability",
            "profile_id",
            "capability_id",
            unique=True,
            postgresql_where=text("capability_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False
    )
    capability_id: Mapped[UUID | None] = mapped_column(ForeignKey("capabilities.id"))
    raw_name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    proficiency: Mapped[str | None] = mapped_column(String(20))
    explicit_experience_months: Mapped[int | None] = mapped_column(Integer)
    evidence_strength: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_start: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_end: Mapped[int] = mapped_column(Integer, nullable=False)
    mapping_method: Mapped[str] = mapped_column(String(30), nullable=False)
    mapping_status: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)


class RecruitmentMatchRun(CreatedAtMixin, Base):
    __tablename__ = "recruitment_match_runs"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "requirements_sha256",
            "candidate_selection_sha256",
            "weight_version",
            name="uq_recruitment_match_runs_inputs",
        ),
        CheckConstraint("requirements_revision >= 1", name="requirements_revision"),
        CheckConstraint("result_count >= 1", name="result_count"),
        CheckConstraint("skipped_count >= 0", name="skipped_count"),
        CheckConstraint("high_count >= 0", name="high_count"),
        CheckConstraint("medium_count >= 0", name="medium_count"),
        CheckConstraint("low_count >= 0", name="low_count"),
        CheckConstraint(
            "high_count + medium_count + low_count = result_count",
            name="level_counts",
        ),
        CheckConstraint(
            "jsonb_typeof(weight_snapshot) = 'object'",
            name="weight_snapshot_object",
        ),
        CheckConstraint(
            "jsonb_typeof(requirements_snapshot) = 'object'",
            name="requirements_snapshot_object",
        ),
        CheckConstraint(
            "jsonb_typeof(skipped_candidates) = 'array'",
            name="skipped_candidates_array",
        ),
        CheckConstraint(
            "jsonb_array_length(skipped_candidates) = skipped_count",
            name="skipped_candidates_count",
        ),
        Index(
            "ix_recruitment_match_runs_project_created",
            "project_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("recruitment_projects.id", ondelete="CASCADE"), nullable=False
    )
    requirements_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    requirements_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    candidate_selection_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    weight_version: Mapped[str] = mapped_column(String(40), nullable=False)
    weight_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    requirements_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    skipped_candidates: Mapped[list] = mapped_column(JSONB, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False)
    high_count: Mapped[int] = mapped_column(Integer, nullable=False)
    medium_count: Mapped[int] = mapped_column(Integer, nullable=False)
    low_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )


class RecruitmentMatchResult(CreatedAtMixin, Base):
    __tablename__ = "recruitment_match_results"
    __table_args__ = (
        UniqueConstraint(
            "match_run_id", "rank", name="uq_recruitment_match_results_run_rank"
        ),
        CheckConstraint("rank >= 1", name="positive_rank"),
        CheckConstraint("total_score BETWEEN 0 AND 100", name="score_range"),
        CheckConstraint("match_level IN ('high','medium','low')", name="match_level"),
        CheckConstraint(
            "jsonb_typeof(dimension_scores) = 'object'",
            name="dimension_scores_object",
        ),
        CheckConstraint(
            "jsonb_typeof(matched_capabilities) = 'array'",
            name="matched_capabilities_array",
        ),
        CheckConstraint(
            "jsonb_typeof(missing_capabilities) = 'array'",
            name="missing_capabilities_array",
        ),
        CheckConstraint(
            "jsonb_typeof(gap_summary) = 'object'",
            name="gap_summary_object",
        ),
        CheckConstraint(
            "jsonb_typeof(candidate_snapshot) = 'object'",
            name="candidate_snapshot_object",
        ),
    )

    match_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("recruitment_match_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("recruitment_candidates.id"), primary_key=True
    )
    candidate_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    total_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    match_level: Mapped[str] = mapped_column(String(20), nullable=False)
    dimension_scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
    matched_capabilities: Mapped[list] = mapped_column(JSONB, nullable=False)
    missing_capabilities: Mapped[list] = mapped_column(JSONB, nullable=False)
    gap_summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
    candidate_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
