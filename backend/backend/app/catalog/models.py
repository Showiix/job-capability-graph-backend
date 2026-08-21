from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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


class Domain(CreatedAtMixin, Base):
    __tablename__ = "domains"
    __table_args__ = (
        UniqueConstraint("code", name="uq_domains_code"),
        CheckConstraint("status IN ('active','deprecated')", name="status"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_self_parent"),
        Index("ix_domains_parent_sort", "parent_id", "sort_order"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("domains.id"))
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class Capability(CreatedAtMixin, Base):
    __tablename__ = "capabilities"
    __table_args__ = (
        UniqueConstraint(
            "domain_id", "canonical_name", name="uq_capabilities_domain_name"
        ),
        CheckConstraint(
            "status IN ('candidate','active','deprecated')",
            name="status",
        ),
        CheckConstraint("length(btrim(canonical_name)) > 0", name="nonempty_name"),
        Index("ix_capabilities_domain_status", "domain_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    domain_id: Mapped[UUID] = mapped_column(ForeignKey("domains.id"), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    skill_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="candidate", server_default="candidate", nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    replacement_capability_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("capabilities.id")
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CapabilityAlias(CreatedAtMixin, Base):
    __tablename__ = "capability_aliases"
    __table_args__ = (
        UniqueConstraint("alias", name="uq_capability_aliases_alias"),
        CheckConstraint("status IN ('active','deprecated','ambiguous')", name="status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    capability_id: Mapped[UUID] = mapped_column(
        ForeignKey("capabilities.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)


class JobRole(CreatedAtMixin, Base):
    __tablename__ = "job_roles"
    __table_args__ = (
        UniqueConstraint(
            "domain_id", "canonical_name", name="uq_job_roles_domain_name"
        ),
        CheckConstraint(
            "status IN ('candidate','active','deprecated')",
            name="status",
        ),
        CheckConstraint("length(btrim(canonical_name)) > 0", name="nonempty_name"),
        CheckConstraint(
            "jsonb_typeof(definition_payload) = 'object'",
            name="definition_payload_object",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    domain_id: Mapped[UUID] = mapped_column(ForeignKey("domains.id"), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    definition_payload: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), default="candidate", server_default="candidate", nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    replacement_job_role_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("job_roles.id")
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class JobRoleAlias(CreatedAtMixin, Base):
    __tablename__ = "job_role_aliases"
    __table_args__ = (UniqueConstraint("alias", name="uq_job_role_aliases_alias"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_role_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_roles.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)


class JobRoleCapability(CreatedAtMixin, Base):
    __tablename__ = "job_role_capabilities"
    __table_args__ = (
        CheckConstraint(
            "requirement_type IN ('required','bonus')",
            name="requirement_type",
        ),
        CheckConstraint("importance BETWEEN 0 AND 1", name="importance"),
        Index(
            "ix_job_role_capabilities_capability_type",
            "capability_id",
            "requirement_type",
        ),
    )

    job_role_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    capability_id: Mapped[UUID] = mapped_column(
        ForeignKey("capabilities.id"),
        primary_key=True,
    )
    requirement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    importance: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    source_candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("graph_change_candidates.id", ondelete="SET NULL")
    )


class CatalogVersion(CreatedAtMixin, Base):
    __tablename__ = "catalog_versions"
    __table_args__ = (
        UniqueConstraint("version_no", name="uq_catalog_versions_version_no"),
        CheckConstraint(
            "status IN ('draft','validated','published','archived')",
            name="status",
        ),
        Index(
            "uq_catalog_versions_current_published",
            "is_current",
            unique=True,
            postgresql_where=text("status = 'published' AND is_current = true"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    summary: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column()


class CatalogVersionItem(CreatedAtMixin, Base):
    __tablename__ = "catalog_version_items"
    __table_args__ = (
        CheckConstraint("item_type IN ('capability','job_role')", name="item_type"),
        CheckConstraint(
            "(item_type = 'capability' AND capability_id IS NOT NULL "
            "AND job_role_id IS NULL) "
            "OR (item_type = 'job_role' AND capability_id IS NULL "
            "AND job_role_id IS NOT NULL)",
            name="one_target",
        ),
        UniqueConstraint(
            "catalog_version_id",
            "item_type",
            "capability_id",
            "job_role_id",
            name="uq_catalog_version_items_target",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    catalog_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalog_versions.id", ondelete="CASCADE"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    capability_id: Mapped[UUID | None] = mapped_column(ForeignKey("capabilities.id"))
    job_role_id: Mapped[UUID | None] = mapped_column(ForeignKey("job_roles.id"))
    change_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="added"
    )


class CatalogImport(CreatedAtMixin, Base):
    __tablename__ = "catalog_imports"
    __table_args__ = (
        CheckConstraint("mode IN ('validate_only','apply')", name="mode"),
        CheckConstraint(
            "status IN ('processing','validated','applied','failed')", name="status"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    uploaded_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    file_id: Mapped[UUID] = mapped_column(ForeignKey("stored_files.id"), nullable=False)
    import_type: Mapped[str] = mapped_column(String(30), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )


class CatalogImportRow(Base):
    __tablename__ = "catalog_import_rows"
    __table_args__ = (
        Index("ix_catalog_import_rows_import_row", "catalog_import_id", "row_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    catalog_import_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalog_imports.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    row_status: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
