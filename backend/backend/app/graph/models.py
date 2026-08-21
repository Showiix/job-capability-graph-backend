from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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


class GraphVersion(CreatedAtMixin, Base):
    __tablename__ = "graph_versions"
    __table_args__ = (
        UniqueConstraint("version_no", name="uq_graph_versions_version_no"),
        UniqueConstraint(
            "source_proposal_id",
            name="uq_graph_versions_source_proposal",
        ),
        UniqueConstraint(
            "catalog_version_id",
            name="uq_graph_versions_catalog_version",
        ),
        UniqueConstraint("job_role_id", name="uq_graph_versions_job_role"),
        CheckConstraint("version_no >= 1", name="positive_version"),
        CheckConstraint("attempt_count >= 0", name="attempt_count"),
        CheckConstraint(
            "status IN ('draft','publishing','published','failed')",
            name="status",
        ),
        CheckConstraint(
            "(status = 'published') = (published_at IS NOT NULL)",
            name="published_at",
        ),
        CheckConstraint(
            "jsonb_typeof(snapshot) = 'object'",
            name="snapshot_object",
        ),
        Index(
            "uq_graph_versions_current_published",
            "is_current",
            unique=True,
            postgresql_where=text("status = 'published' AND is_current = true"),
        ),
        Index("ix_graph_versions_status_created", "status", text("created_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_proposal_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_change_candidates.id"),
        nullable=False,
    )
    catalog_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalog_versions.id"),
        nullable=False,
    )
    job_role_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        nullable=False,
    )
    snapshot: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
