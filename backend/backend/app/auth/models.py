from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base, CreatedAtMixin


class User(CreatedAtMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('applicant','hr','admin')", name="role"),
        CheckConstraint(
            "length(username_normalized) BETWEEN 3 AND 64",
            name="username_length",
        ),
        Index(
            "ix_users_active_role_created_at",
            "role",
            text("created_at DESC"),
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    username_normalized: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=true(),
        nullable=False,
    )
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AuthSession(CreatedAtMixin, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        Index("ix_auth_sessions_user_expiry", "user_id", text("expires_at DESC")),
        Index(
            "ix_auth_sessions_active_expiry",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True, nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(500))


class LoginAttempt(CreatedAtMixin, Base):
    __tablename__ = "login_attempts"
    __table_args__ = (
        Index(
            "ix_login_attempts_username_created",
            "username_normalized",
            text("created_at DESC"),
        ),
        Index(
            "ix_login_attempts_ip_created",
            "ip_address",
            text("created_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username_normalized: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(50))
    ip_address: Mapped[str | None] = mapped_column(INET)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
