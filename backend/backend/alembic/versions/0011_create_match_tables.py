"""create match tables

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "match_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("resume_id", sa.Uuid(), nullable=False),
        sa.Column("resume_profile_id", sa.Uuid(), nullable=False),
        sa.Column("graph_version_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_version_id", sa.Uuid(), nullable=False),
        sa.Column("weight_version", sa.String(length=40), nullable=False),
        sa.Column(
            "weight_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("high_count", sa.Integer(), nullable=False),
        sa.Column("medium_count", sa.Integer(), nullable=False),
        sa.Column("low_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("high_count >= 0", name=op.f("ck_match_runs_high_count")),
        sa.CheckConstraint(
            "high_count + medium_count + low_count = result_count",
            name=op.f("ck_match_runs_level_counts"),
        ),
        sa.CheckConstraint("low_count >= 0", name=op.f("ck_match_runs_low_count")),
        sa.CheckConstraint(
            "medium_count >= 0", name=op.f("ck_match_runs_medium_count")
        ),
        sa.CheckConstraint(
            "result_count >= 0", name=op.f("ck_match_runs_result_count")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(weight_snapshot) = 'object'",
            name=op.f("ck_match_runs_weight_snapshot_object"),
        ),
        sa.ForeignKeyConstraint(
            ["catalog_version_id"],
            ["catalog_versions.id"],
            name=op.f("fk_match_runs_catalog_version_id_catalog_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["graph_version_id"],
            ["graph_versions.id"],
            name=op.f("fk_match_runs_graph_version_id_graph_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_match_runs_owner_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["resume_id"],
            ["resumes.id"],
            name=op.f("fk_match_runs_resume_id_resumes"),
        ),
        sa.ForeignKeyConstraint(
            ["resume_profile_id"],
            ["resume_profiles.id"],
            name=op.f("fk_match_runs_resume_profile_id_resume_profiles"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_match_runs")),
        sa.UniqueConstraint(
            "resume_profile_id",
            "graph_version_id",
            "weight_version",
            name="uq_match_runs_profile_graph_weight",
        ),
    )
    op.create_index(
        "ix_match_runs_owner_created",
        "match_runs",
        ["owner_user_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_match_runs_resume_created",
        "match_runs",
        ["resume_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "match_results",
        sa.Column("match_run_id", sa.Uuid(), nullable=False),
        sa.Column("job_role_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("total_score", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("match_level", sa.String(length=20), nullable=False),
        sa.Column(
            "dimension_scores",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "matched_capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "missing_capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "gap_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "job_role_snapshot",
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
            "jsonb_typeof(dimension_scores) = 'object'",
            name=op.f("ck_match_results_dimension_scores_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(gap_summary) = 'object'",
            name=op.f("ck_match_results_gap_summary_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(job_role_snapshot) = 'object'",
            name=op.f("ck_match_results_job_role_snapshot_object"),
        ),
        sa.CheckConstraint(
            "match_level IN ('high','medium','low')",
            name=op.f("ck_match_results_match_level"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(matched_capabilities) = 'array'",
            name=op.f("ck_match_results_matched_capabilities_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(missing_capabilities) = 'array'",
            name=op.f("ck_match_results_missing_capabilities_array"),
        ),
        sa.CheckConstraint("rank >= 1", name=op.f("ck_match_results_positive_rank")),
        sa.CheckConstraint(
            "total_score BETWEEN 0 AND 100",
            name=op.f("ck_match_results_score_range"),
        ),
        sa.ForeignKeyConstraint(
            ["job_role_id"],
            ["job_roles.id"],
            name=op.f("fk_match_results_job_role_id_job_roles"),
        ),
        sa.ForeignKeyConstraint(
            ["match_run_id"],
            ["match_runs.id"],
            name=op.f("fk_match_results_match_run_id_match_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "match_run_id",
            "job_role_id",
            name=op.f("pk_match_results"),
        ),
        sa.UniqueConstraint(
            "match_run_id",
            "rank",
            name="uq_match_results_run_rank",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("match_results")
    op.drop_index("ix_match_runs_resume_created", table_name="match_runs")
    op.drop_index("ix_match_runs_owner_created", table_name="match_runs")
    op.drop_table("match_runs")
