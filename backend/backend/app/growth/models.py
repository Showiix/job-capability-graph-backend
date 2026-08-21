from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base, CreatedAtMixin


class GrowthPath(CreatedAtMixin, Base):
    __tablename__ = "growth_paths"
    __table_args__ = (
        ForeignKeyConstraint(
            ["match_run_id", "job_role_id"],
            ["match_results.match_run_id", "match_results.job_role_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "match_run_id",
            "job_role_id",
            "prompt_version",
            name="uq_growth_paths_match_role_prompt",
        ),
        CheckConstraint(
            "jsonb_typeof(source_snapshot) = 'object'",
            name="source_object",
        ),
        CheckConstraint(
            "jsonb_typeof(path_payload) = 'object'",
            name="path_object",
        ),
        CheckConstraint(
            "jsonb_typeof(generation_metadata) = 'object'",
            name="metadata_object",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    match_run_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    job_role_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    source_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    path_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    generation_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False)
