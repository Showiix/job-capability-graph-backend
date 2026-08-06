from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
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


class Resume(CreatedAtMixin, Base):
    __tablename__ = "resumes"
    __table_args__ = (
        UniqueConstraint("file_id", name="uq_resumes_file_id"),
        CheckConstraint(
            "parse_status IN ('uploaded','processing','ready','failed','archived')",
            name="parse_status",
        ),
        CheckConstraint(
            "(parse_status = 'archived') = (archived_at IS NOT NULL)",
            name="archived_at",
        ),
        CheckConstraint(
            "created_by_user_id = owner_user_id",
            name="creator_is_owner",
        ),
        Index("ix_resumes_owner_created", "owner_user_id", text("created_at DESC")),
        Index("ix_resumes_status_updated", "parse_status", text("updated_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    file_id: Mapped[UUID] = mapped_column(ForeignKey("stored_files.id"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_language: Mapped[str] = mapped_column(
        String(20), default="zh-CN", server_default="zh-CN", nullable=False
    )
    parse_status: Mapped[str] = mapped_column(
        String(30), default="uploaded", server_default="uploaded", nullable=False
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
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResumeProfile(CreatedAtMixin, Base):
    __tablename__ = "resume_profiles"
    __table_args__ = (
        UniqueConstraint("resume_id", "version_no", name="uq_resume_profiles_version"),
        CheckConstraint("version_no >= 1", name="positive_version"),
        CheckConstraint(
            "profile_source IN ('extracted','manual_revision')", name="profile_source"
        ),
        CheckConstraint(
            "text_extraction_method IN ('pdf_text','docx')", name="extraction_method"
        ),
        CheckConstraint(
            "status IN ('candidate','draft','confirmed','superseded')", name="status"
        ),
        CheckConstraint(
            "total_experience_months IS NULL OR total_experience_months >= 0",
            name="experience_months",
        ),
        CheckConstraint(
            "(status IN ('confirmed','superseded')) = (confirmed_at IS NOT NULL)",
            name="confirmed_at",
        ),
        CheckConstraint(
            "(profile_source = 'extracted' AND created_by_run_id IS NOT NULL "
            "AND base_profile_id IS NULL) OR "
            "(profile_source = 'manual_revision' AND created_by_run_id IS NULL "
            "AND base_profile_id IS NOT NULL)",
            name="source_links",
        ),
        CheckConstraint(
            "(profile_source = 'extracted' AND "
            "status IN ('candidate','confirmed','superseded')) OR "
            "(profile_source = 'manual_revision' AND "
            "status IN ('draft','confirmed','superseded'))",
            name="source_status",
        ),
        CheckConstraint(
            "base_profile_id IS NULL OR base_profile_id <> id", name="not_self_base"
        ),
        Index(
            "uq_resume_profiles_extraction",
            "resume_id",
            "extraction_version",
            unique=True,
            postgresql_where=text("profile_source = 'extracted'"),
        ),
        Index(
            "uq_resume_profiles_confirmed",
            "resume_id",
            unique=True,
            postgresql_where=text("status = 'confirmed'"),
        ),
        Index(
            "ix_resume_profiles_resume_version", "resume_id", text("version_no DESC")
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    resume_id: Mapped[UUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False
    )
    base_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("resume_profiles.id")
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    extraction_version: Mapped[str] = mapped_column(String(80), nullable=False)
    profile_source: Mapped[str] = mapped_column(String(20), nullable=False)
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
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_by_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("processing_runs.id")
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ResumeSkill(CreatedAtMixin, Base):
    __tablename__ = "resume_skills"
    __table_args__ = (
        UniqueConstraint("profile_id", "normalized_name", name="uq_resume_skills_name"),
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
            "mapping_method IN ('canonical_exact','alias_exact','manual','unmapped')",
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
            "('canonical_exact','alias_exact','manual')) OR "
            "(mapping_status = 'unmapped' AND mapping_method = 'unmapped')",
            name="mapping_combination",
        ),
        CheckConstraint("source IN ('llm','manual')", name="source"),
        CheckConstraint(
            "(source = 'llm' AND mapping_method IN "
            "('canonical_exact','alias_exact','unmapped')) OR "
            "(source = 'manual' AND mapping_method IN ('manual','unmapped'))",
            name="source_mapping",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence"),
        CheckConstraint(
            "(source = 'llm' AND evidence_quote IS NOT NULL "
            "AND evidence_start IS NOT NULL AND evidence_end IS NOT NULL "
            "AND user_confirmed = false) OR "
            "(source = 'manual' AND user_confirmed = true)",
            name="source_evidence",
        ),
        CheckConstraint(
            "(evidence_start IS NULL AND evidence_end IS NULL) OR "
            "(evidence_start >= 0 AND evidence_end > evidence_start)",
            name="evidence_offsets",
        ),
        Index("ix_resume_skills_mapping", "profile_id", "mapping_status"),
        Index(
            "ix_resume_skills_capability",
            "capability_id",
            postgresql_where=text("capability_id IS NOT NULL"),
        ),
        Index(
            "uq_resume_skills_profile_capability",
            "profile_id",
            "capability_id",
            unique=True,
            postgresql_where=text("capability_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("resume_profiles.id", ondelete="CASCADE"), nullable=False
    )
    capability_id: Mapped[UUID | None] = mapped_column(ForeignKey("capabilities.id"))
    raw_name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    proficiency: Mapped[str | None] = mapped_column(String(20))
    explicit_experience_months: Mapped[int | None] = mapped_column(Integer)
    evidence_strength: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    evidence_start: Mapped[int | None] = mapped_column(Integer)
    evidence_end: Mapped[int | None] = mapped_column(Integer)
    mapping_method: Mapped[str] = mapped_column(String(30), nullable=False)
    mapping_status: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    user_confirmed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
