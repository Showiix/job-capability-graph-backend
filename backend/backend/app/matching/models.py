from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base, CreatedAtMixin


class MatchRun(CreatedAtMixin, Base):
    __tablename__ = "match_runs"
    __table_args__ = (
        UniqueConstraint(
            "resume_profile_id",
            "graph_version_id",
            "weight_version",
            name="uq_match_runs_profile_graph_weight",
        ),
        CheckConstraint("result_count >= 0", name="result_count"),
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
        Index(
            "ix_match_runs_owner_created",
            "owner_user_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_match_runs_resume_created",
            "resume_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    resume_id: Mapped[UUID] = mapped_column(ForeignKey("resumes.id"), nullable=False)
    resume_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("resume_profiles.id"), nullable=False
    )
    graph_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_versions.id"), nullable=False
    )
    catalog_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalog_versions.id"), nullable=False
    )
    weight_version: Mapped[str] = mapped_column(String(40), nullable=False)
    weight_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    high_count: Mapped[int] = mapped_column(Integer, nullable=False)
    medium_count: Mapped[int] = mapped_column(Integer, nullable=False)
    low_count: Mapped[int] = mapped_column(Integer, nullable=False)


class MatchResult(CreatedAtMixin, Base):
    __tablename__ = "match_results"
    __table_args__ = (
        UniqueConstraint("match_run_id", "rank", name="uq_match_results_run_rank"),
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
            "jsonb_typeof(job_role_snapshot) = 'object'",
            name="job_role_snapshot_object",
        ),
    )

    match_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("match_runs.id", ondelete="CASCADE"), primary_key=True
    )
    job_role_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_roles.id"), primary_key=True
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    total_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    match_level: Mapped[str] = mapped_column(String(20), nullable=False)
    dimension_scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
    matched_capabilities: Mapped[list] = mapped_column(JSONB, nullable=False)
    missing_capabilities: Mapped[list] = mapped_column(JSONB, nullable=False)
    gap_summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
    job_role_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
