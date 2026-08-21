from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base, CreatedAtMixin

BOUNDED_DECIMAL = Numeric(5, 4)


class JobAnalysisProfile(CreatedAtMixin, Base):
    __tablename__ = "job_analysis_profiles"
    __table_args__ = (
        UniqueConstraint(
            "normalized_job_id",
            "version_no",
            name="uq_job_analysis_profiles_job_version",
        ),
        UniqueConstraint(
            "normalized_job_id",
            "extraction_version",
            name="uq_job_analysis_profiles_job_extraction",
        ),
        CheckConstraint(
            "status IN ('candidate','validated','invalid')",
            name="status",
        ),
        CheckConstraint("version_no >= 1", name="positive_version"),
        Index("ix_job_analysis_profiles_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    normalized_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("normalized_job_postings.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
    )
    extraction_version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    structured_payload: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    validation_errors: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    created_by_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("processing_runs.id"),
        nullable=False,
    )


class JobSkillCandidate(CreatedAtMixin, Base):
    __tablename__ = "job_skill_candidates"
    __table_args__ = (
        UniqueConstraint(
            "analysis_profile_id",
            "normalized_name",
            name="uq_job_skill_candidates_profile_name",
        ),
        CheckConstraint(
            "requirement_type IN ('required','preferred')",
            name="requirement_type",
        ),
        CheckConstraint("importance BETWEEN 0 AND 1", name="importance"),
        CheckConstraint(
            "required_level IS NULL OR required_level IN "
            "('beginner','intermediate','advanced')",
            name="required_level",
        ),
        CheckConstraint(
            "mapping_method IN ('canonical_exact','alias_exact','normalized_exact',"
            "'semantic_candidate','manual','unmapped')",
            name="mapping_method",
        ),
        CheckConstraint(
            "mapping_status IN ('mapped','ambiguous','unmapped','invalid')",
            name="mapping_status",
        ),
        CheckConstraint(
            "extraction_source IN ('algorithm','llm','merged','manual')",
            name="extraction_source",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence"),
        CheckConstraint(
            "(mapping_status = 'mapped') = (capability_id IS NOT NULL)",
            name="mapping_capability",
        ),
        Index(
            "ix_job_skill_candidates_profile_requirement",
            "analysis_profile_id",
            "requirement_type",
        ),
        Index(
            "ix_job_skill_candidates_capability",
            "capability_id",
            postgresql_where=text("capability_id IS NOT NULL"),
        ),
        Index(
            "ix_job_skill_candidates_mapping_created",
            "mapping_status",
            text("created_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    analysis_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_analysis_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    capability_id: Mapped[UUID | None] = mapped_column(ForeignKey("capabilities.id"))
    raw_name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    requirement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    importance: Mapped[Decimal] = mapped_column(BOUNDED_DECIMAL, nullable=False)
    required_level: Mapped[str | None] = mapped_column(String(20))
    mapping_method: Mapped[str] = mapped_column(String(30), nullable=False)
    mapping_status: Mapped[str] = mapped_column(String(20), nullable=False)
    extraction_source: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(BOUNDED_DECIMAL, nullable=False)


class DiscoveryRun(CreatedAtMixin, Base):
    __tablename__ = "discovery_runs"
    __table_args__ = (
        UniqueConstraint("processing_run_id", name="uq_discovery_runs_processing_run"),
        CheckConstraint(
            "status IN ('pending','running','completed','failed','cancelled')",
            name="status",
        ),
        Index("ix_discovery_runs_created", text("created_at DESC")),
        Index("ix_discovery_runs_status_created", "status", text("created_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    processing_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    input_batch_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid),
        nullable=False,
    )
    current_catalog_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("catalog_versions.id")
    )
    algorithm_version: Mapped[str] = mapped_column(String(80), nullable=False)
    extraction_version: Mapped[str] = mapped_column(String(80), nullable=False)
    parameters: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SkillCombinationCandidate(CreatedAtMixin, Base):
    __tablename__ = "skill_combination_candidates"
    __table_args__ = (
        UniqueConstraint(
            "discovery_run_id",
            "normalized_name",
            name="uq_skill_combination_candidates_run_name",
        ),
        CheckConstraint("length(btrim(suggested_name)) > 0", name="nonempty_name"),
        CheckConstraint("support_job_count >= 0", name="support_job_count"),
        CheckConstraint("source_count >= 0", name="source_count"),
        CheckConstraint("company_count >= 0", name="company_count"),
        CheckConstraint("support_score BETWEEN 0 AND 1", name="support_score"),
        CheckConstraint("diversity_score BETWEEN 0 AND 1", name="diversity_score"),
        CheckConstraint("coherence_score BETWEEN 0 AND 1", name="coherence_score"),
        CheckConstraint("novelty_score BETWEEN 0 AND 1", name="novelty_score"),
        CheckConstraint("evidence_score BETWEEN 0 AND 1", name="evidence_score"),
        CheckConstraint(
            "overall_candidate_score BETWEEN 0 AND 1",
            name="overall_candidate_score",
        ),
        CheckConstraint(
            "status IN ('candidate','feedback_collected','proposed_for_review',"
            "'rejected')",
            name="status",
        ),
        Index(
            "ix_skill_combination_candidates_run_score",
            "discovery_run_id",
            text("overall_candidate_score DESC"),
        ),
        Index("ix_skill_combination_candidates_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    discovery_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    suggested_name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    definition_payload: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    support_job_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    company_count: Mapped[int] = mapped_column(Integer, nullable=False)
    support_score: Mapped[Decimal] = mapped_column(BOUNDED_DECIMAL, nullable=False)
    diversity_score: Mapped[Decimal] = mapped_column(BOUNDED_DECIMAL, nullable=False)
    coherence_score: Mapped[Decimal] = mapped_column(BOUNDED_DECIMAL, nullable=False)
    novelty_score: Mapped[Decimal] = mapped_column(BOUNDED_DECIMAL, nullable=False)
    evidence_score: Mapped[Decimal] = mapped_column(BOUNDED_DECIMAL, nullable=False)
    overall_candidate_score: Mapped[Decimal] = mapped_column(
        BOUNDED_DECIMAL,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)


class CombinationSkill(Base):
    __tablename__ = "combination_skills"
    __table_args__ = (
        CheckConstraint("skill_role IN ('core','bonus')", name="skill_role"),
        CheckConstraint("weight BETWEEN 0 AND 1", name="weight"),
        CheckConstraint("frequency BETWEEN 0 AND 1", name="frequency"),
    )

    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("skill_combination_candidates.id", ondelete="CASCADE"),
        primary_key=True,
    )
    capability_id: Mapped[UUID] = mapped_column(
        ForeignKey("capabilities.id"),
        primary_key=True,
    )
    skill_role: Mapped[str] = mapped_column(String(20), nullable=False)
    weight: Mapped[Decimal] = mapped_column(BOUNDED_DECIMAL, nullable=False)
    frequency: Mapped[Decimal] = mapped_column(BOUNDED_DECIMAL, nullable=False)


class CombinationEvidence(Base):
    __tablename__ = "combination_evidence"
    __table_args__ = (
        CheckConstraint("evidence_weight BETWEEN 0 AND 1", name="evidence_weight"),
    )

    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("skill_combination_candidates.id", ondelete="CASCADE"),
        primary_key=True,
    )
    normalized_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("normalized_job_postings.id", ondelete="CASCADE"),
        primary_key=True,
    )
    evidence_weight: Mapped[Decimal] = mapped_column(BOUNDED_DECIMAL, nullable=False)
    representative: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        nullable=False,
    )
