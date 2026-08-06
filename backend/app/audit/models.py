from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Uuid, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base, CreatedAtMixin


class AuditLog(CreatedAtMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("outcome IN ('success','denied','failed')", name="outcome"),
        Index(
            "ix_audit_logs_actor_created",
            "actor_user_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_audit_logs_resource_created",
            "resource_type",
            "resource_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_audit_logs_action_created",
            "action",
            text("created_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(Uuid)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    processing_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("processing_runs.id")
    )
    ip_address: Mapped[str | None] = mapped_column(INET)
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
