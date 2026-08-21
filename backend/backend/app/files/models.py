from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base, CreatedAtMixin


class StoredFile(CreatedAtMixin, Base):
    __tablename__ = "stored_files"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="positive_size"),
        CheckConstraint(
            "category IN ('market_jd','catalog','resume','jd','portfolio','other')",
            name="category",
        ),
        CheckConstraint(
            "scan_status IN ('pending','clean','rejected','not_required')",
            name="scan_status",
        ),
        CheckConstraint(
            "status IN ('uploaded','attached','archived','deleted')",
            name="status",
        ),
        Index(
            "ix_stored_files_uploader_created",
            "uploaded_by_user_id",
            text("created_at DESC"),
        ),
        Index("ix_stored_files_hash_size", "sha256", "size_bytes"),
        Index(
            "ix_stored_files_expiring_unattached",
            "expires_at",
            postgresql_where=text("status = 'uploaded' AND expires_at IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    uploaded_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )
    media_type: Mapped[str] = mapped_column(String(150), nullable=False)
    extension: Mapped[str] = mapped_column(String(20), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    scan_status: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FileAccessLog(CreatedAtMixin, Base):
    __tablename__ = "file_access_logs"
    __table_args__ = (
        CheckConstraint("action IN ('preview','download')", name="action"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("stored_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
