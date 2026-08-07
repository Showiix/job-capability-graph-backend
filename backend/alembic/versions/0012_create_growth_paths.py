"""create growth paths table

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "growth_paths",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_run_id", sa.Uuid(), nullable=False),
        sa.Column("job_role_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column(
            "source_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "path_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "generation_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_snapshot) = 'object'",
            name=op.f("ck_growth_paths_source_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(path_payload) = 'object'",
            name=op.f("ck_growth_paths_path_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(generation_metadata) = 'object'",
            name=op.f("ck_growth_paths_metadata_object"),
        ),
        sa.ForeignKeyConstraint(
            ["match_run_id", "job_role_id"],
            ["match_results.match_run_id", "match_results.job_role_id"],
            name=op.f("fk_growth_paths_match_run_id_match_results"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_growth_paths")),
        sa.UniqueConstraint(
            "match_run_id",
            "job_role_id",
            "prompt_version",
            name="uq_growth_paths_match_role_prompt",
        ),
    )


def downgrade() -> None:
    op.drop_table("growth_paths")
