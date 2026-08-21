from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base, CreatedAtMixin


class DataSource(CreatedAtMixin, Base):
    __tablename__ = "data_sources"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('file_import','crawler','manual')",
            name="source_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    adapter_code: Mapped[str] = mapped_column(String(80), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(40), nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=true(),
        nullable=False,
    )
    config: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ImportBatch(CreatedAtMixin, Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded','processing','processed','partial','failed',"
            "'archived')",
            name="status",
        ),
        CheckConstraint(
            "total_rows >= 0 AND accepted_rows >= 0 AND rejected_rows >= 0 "
            "AND warning_rows >= 0",
            name="nonnegative_counts",
        ),
        CheckConstraint(
            "accepted_rows + rejected_rows <= total_rows",
            name="resolved_counts",
        ),
        Index("ix_import_batches_created", text("created_at DESC")),
        Index(
            "ix_import_batches_source_collected",
            "source_id",
            text("collected_at DESC"),
        ),
        Index(
            "ix_import_batches_status_created",
            "status",
            text("created_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("data_sources.id"),
        nullable=False,
    )
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("stored_files.id"),
        nullable=False,
    )
    uploaded_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )
    detected_adapter_code: Mapped[str | None] = mapped_column(String(80))
    adapter_version: Mapped[str | None] = mapped_column(String(40))
    schema_version: Mapped[str | None] = mapped_column(String(40))
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default="uploaded",
        server_default="uploaded",
        nullable=False,
    )
    total_rows: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    accepted_rows: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    rejected_rows: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    warning_rows: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    batch_summary: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RawJobPosting(CreatedAtMixin, Base):
    __tablename__ = "raw_job_postings"
    __table_args__ = (
        UniqueConstraint("batch_id", "row_number", name="uq_raw_job_batch_row"),
        CheckConstraint("row_number >= 1", name="positive_row_number"),
        CheckConstraint("length(btrim(job_name)) > 0", name="nonempty_job_name"),
        Index("ix_raw_job_batch_row", "batch_id", "row_number"),
        Index("ix_raw_job_source_external", "source_code", "external_id"),
        Index(
            "ix_raw_job_content_hash",
            "content_hash",
            postgresql_where=text("content_hash IS NOT NULL"),
        ),
        Index(
            "ix_raw_job_source_url",
            "source_url",
            postgresql_where=text("source_url IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_code: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(150))
    source_url: Mapped[str | None] = mapped_column(Text)
    job_name: Mapped[str] = mapped_column(Text, nullable=False)
    company_name: Mapped[str | None] = mapped_column(Text)
    salary_text: Mapped[str | None] = mapped_column(Text)
    work_area_text: Mapped[str | None] = mapped_column(Text)
    city_text: Mapped[str | None] = mapped_column(Text)
    education_text: Mapped[str | None] = mapped_column(Text)
    work_year_text: Mapped[str | None] = mapped_column(Text)
    issue_date_text: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str | None] = mapped_column(Text)
    source_tags: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    raw_payload: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    source_encoding: Mapped[str | None] = mapped_column(String(30))
    parse_warnings: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    content_hash: Mapped[str | None] = mapped_column(CHAR(64))


class NormalizedJobPosting(CreatedAtMixin, Base):
    __tablename__ = "normalized_job_postings"
    __table_args__ = (
        UniqueConstraint(
            "raw_job_id",
            "version_no",
            name="uq_normalized_job_version",
        ),
        CheckConstraint("version_no >= 1", name="positive_version"),
        CheckConstraint("quality_score BETWEEN 0 AND 100", name="quality_score"),
        CheckConstraint(
            "salary_min_monthly IS NULL OR salary_min_monthly >= 0",
            name="salary_min",
        ),
        CheckConstraint(
            "salary_max_monthly IS NULL OR "
            "salary_max_monthly >= salary_min_monthly",
            name="salary_range",
        ),
        CheckConstraint(
            "experience_min_months IS NULL OR experience_min_months >= 0",
            name="experience_min",
        ),
        CheckConstraint(
            "experience_max_months IS NULL OR "
            "experience_max_months >= experience_min_months",
            name="experience_range",
        ),
        Index(
            "uq_normalized_job_current",
            "raw_job_id",
            unique=True,
            postgresql_where=text("is_current = true"),
        ),
        Index("ix_normalized_job_published", text("published_at DESC")),
        Index(
            "ix_normalized_job_city_published",
            "city_code",
            text("published_at DESC"),
        ),
        Index("ix_normalized_job_quality", text("quality_score DESC")),
        Index("ix_normalized_job_duplicate", "duplicate_of_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    raw_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw_job_postings.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(300), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(300))
    city_code: Mapped[str | None] = mapped_column(String(30))
    city_name: Mapped[str | None] = mapped_column(String(100))
    work_area: Mapped[str | None] = mapped_column(String(200))
    salary_min_monthly: Mapped[int | None] = mapped_column(Integer)
    salary_max_monthly: Mapped[int | None] = mapped_column(Integer)
    salary_months: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    education_level: Mapped[str | None] = mapped_column(String(30))
    experience_min_months: Mapped[int | None] = mapped_column(Integer)
    experience_max_months: Mapped[int | None] = mapped_column(Integer)
    published_at: Mapped[date | None] = mapped_column(Date)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    quality_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    quality_flags: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    duplicate_of_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("normalized_job_postings.id", ondelete="SET NULL")
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=true(),
        nullable=False,
    )
    created_by_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("processing_runs.id")
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
