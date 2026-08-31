from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
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

BOUNDED_DECIMAL = Numeric(5, 4)


class GraphChangeCandidate(CreatedAtMixin, Base):
    __tablename__ = "graph_change_candidates"
    __table_args__ = (
        UniqueConstraint(
            "source_candidate_id",
            name="uq_graph_change_candidates_source_candidate",
        ),
        CheckConstraint(
            "change_type IN ('create_job_role','skill_added','ai_skill_added',"
            "'skill_declining','weight_increased','weight_decreased',"
            "'promoted_to_required','demoted_to_bonus','skill_obsoleted')",
            name="change_type",
        ),
        CheckConstraint(
            "review_status IN "
            "('pending','needs_revision','approved','rejected','published')",
            name="review_status",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence"),
        CheckConstraint(
            "jsonb_typeof(proposed_payload) = 'object'",
            name="proposed_payload_object",
        ),
        CheckConstraint(
            "jsonb_typeof(source_snapshot) = 'object'",
            name="source_snapshot_object",
        ),
        CheckConstraint(
            "jsonb_typeof(evidence_summary) = 'object'",
            name="evidence_summary_object",
        ),
        Index(
            "ix_graph_change_candidates_status_created",
            "review_status",
            text("created_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("skill_combination_candidates.id", ondelete="SET NULL")
    )
    change_type: Mapped[str] = mapped_column(String(40), nullable=False)
    proposed_payload: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    source_snapshot: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    evidence_summary: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    confidence: Mapped[Decimal] = mapped_column(BOUNDED_DECIMAL, nullable=False)
    review_status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ReviewDecision(CreatedAtMixin, Base):
    __tablename__ = "review_decisions"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('approve','revise','reject')",
            name="decision",
        ),
        CheckConstraint(
            "jsonb_typeof(before_payload) = 'object'",
            name="before_payload_object",
        ),
        CheckConstraint(
            "jsonb_typeof(after_payload) = 'object'",
            name="after_payload_object",
        ),
        Index(
            "ix_review_decisions_candidate_created",
            "graph_change_candidate_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    graph_change_candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_change_candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    reviewer_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    before_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    after_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
