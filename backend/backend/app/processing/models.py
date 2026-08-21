from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    Boolean,
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
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base, CreatedAtMixin

PROCESSING_SCOPE_CHECK = """
(owner_scope_type = 'admin_global' AND owner_scope_id IS NULL)
OR (owner_scope_type IN ('user','recruitment_project') AND owner_scope_id IS NOT NULL)
"""


class ProcessingRun(CreatedAtMixin, Base):
    __tablename__ = "processing_runs"
    __table_args__ = (
        CheckConstraint(
            "owner_scope_type IN ('user','recruitment_project','admin_global')",
            name="owner_scope_type",
        ),
        CheckConstraint(PROCESSING_SCOPE_CHECK, name="owner_scope_id"),
        CheckConstraint(
            "status IN ('pending','enqueue_failed','running','waiting_review',"
            "'cancel_requested','completed','failed','cancelled')",
            name="status",
        ),
        CheckConstraint("total_count >= 0", name="total_count"),
        CheckConstraint(
            "processed_count >= 0 AND processed_count <= total_count",
            name="processed_count",
        ),
        CheckConstraint(
            "success_count >= 0 AND failed_count >= 0",
            name="result_counts",
        ),
        CheckConstraint(
            "progress_percent BETWEEN 0 AND 100",
            name="progress",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts >= 1",
            name="attempts",
        ),
        Index(
            "ix_processing_runs_creator_created",
            "created_by_user_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_processing_runs_scope_created",
            "owner_scope_type",
            "owner_scope_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_processing_runs_subject_created",
            "subject_type",
            "subject_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_processing_runs_pending",
            "created_at",
            postgresql_where=text("status IN ('pending','enqueue_failed')"),
        ),
        Index(
            "ix_processing_runs_running_heartbeat",
            "heartbeat_at",
            postgresql_where=text("status = 'running'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_type: Mapped[str] = mapped_column(String(60), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    retry_of_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("processing_runs.id")
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )
    owner_scope_type: Mapped[str] = mapped_column(String(30), nullable=False)
    owner_scope_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(
        String(30),
        default="pending",
        server_default="pending",
        nullable=False,
    )
    current_stage: Mapped[str | None] = mapped_column(String(60))
    pipeline_version: Mapped[str] = mapped_column(String(80), nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(100))
    total_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    processed_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    success_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    failed_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    progress_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        default=0,
        server_default="0",
        nullable=False,
    )
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
    )
    input_snapshot: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    result_summary: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ProcessingError(Base):
    __tablename__ = "processing_errors"
    __table_args__ = (
        Index("ix_processing_errors_run_occurred", "run_id", "occurred_at"),
        Index(
            "ix_processing_errors_run_stage_retryable",
            "run_id",
            "stage",
            "retryable",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    stage: Mapped[str] = mapped_column(String(60), nullable=False)
    item_type: Mapped[str | None] = mapped_column(String(50))
    item_id: Mapped[UUID | None] = mapped_column(Uuid)
    item_key: Mapped[str | None] = mapped_column(String(200))
    error_code: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class IdempotencyRecord(CreatedAtMixin, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "endpoint_key",
            "idempotency_key",
            name="uq_idempotency_scope_key",
        ),
        CheckConstraint(
            "state IN ('processing','completed','failed')",
            name="state",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    endpoint_key: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    resource_type: Mapped[str | None] = mapped_column(String(50))
    resource_id: Mapped[UUID | None] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
