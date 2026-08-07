"""create recruitment matching tables

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recruitment_projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("jd_source_type", sa.String(length=20)),
        sa.Column("jd_file_id", sa.Uuid()),
        sa.Column("jd_source_text", sa.Text()),
        sa.Column(
            "jd_parse_status",
            sa.String(length=20),
            server_default="empty",
            nullable=False,
        ),
        sa.Column(
            "jd_draft_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "confirmed_requirement_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("confirmed_requirement_sha256", sa.CHAR(length=64)),
        sa.Column(
            "requirements_revision",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("latest_jd_run_id", sa.Uuid()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jd_source_type IS NULL OR jd_source_type IN ('text','file')",
            name=op.f("ck_recruitment_projects_jd_source_type"),
        ),
        sa.CheckConstraint(
            "jd_parse_status IN ('empty','processing','ready','failed')",
            name=op.f("ck_recruitment_projects_jd_parse_status"),
        ),
        sa.CheckConstraint(
            "requirements_revision >= 0",
            name=op.f("ck_recruitment_projects_requirements_revision"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(jd_draft_payload) = 'object'",
            name=op.f("ck_recruitment_projects_jd_draft_payload_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(confirmed_requirement_snapshot) = 'object'",
            name=op.f("ck_recruitment_projects_confirmed_requirement_snapshot_object"),
        ),
        sa.CheckConstraint(
            "(requirements_revision = 0 AND confirmed_requirement_sha256 IS NULL "
            "AND confirmed_requirement_snapshot = '{}'::jsonb) OR "
            "(requirements_revision >= 1 AND confirmed_requirement_sha256 IS NOT NULL "
            "AND confirmed_requirement_snapshot <> '{}'::jsonb)",
            name=op.f("ck_recruitment_projects_confirmed_requirement_revision"),
        ),
        sa.CheckConstraint(
            "(jd_source_type IS NULL AND jd_file_id IS NULL) OR "
            "(jd_source_type = 'text' AND jd_file_id IS NULL) OR "
            "(jd_source_type = 'file' AND jd_file_id IS NOT NULL)",
            name=op.f("ck_recruitment_projects_jd_source_file"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_recruitment_projects_owner_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["jd_file_id"],
            ["stored_files.id"],
            name=op.f("fk_recruitment_projects_jd_file_id_stored_files"),
        ),
        sa.ForeignKeyConstraint(
            ["latest_jd_run_id"],
            ["processing_runs.id"],
            name=op.f("fk_recruitment_projects_latest_jd_run_id_processing_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recruitment_projects")),
    )
    op.create_index(
        "ix_recruitment_projects_owner_created",
        "recruitment_projects",
        ["owner_user_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_recruitment_projects_status_updated",
        "recruitment_projects",
        ["jd_parse_status", sa.literal_column("updated_at DESC")],
        unique=False,
    )

    op.create_table(
        "recruitment_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column(
            "parse_status",
            sa.String(length=20),
            server_default="uploaded",
            nullable=False,
        ),
        sa.Column("latest_run_id", sa.Uuid()),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "parse_status IN ('uploaded','processing','ready','failed')",
            name=op.f("ck_recruitment_candidates_parse_status"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["recruitment_projects.id"],
            name=op.f("fk_recruitment_candidates_project_id_recruitment_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["stored_files.id"],
            name=op.f("fk_recruitment_candidates_file_id_stored_files"),
        ),
        sa.ForeignKeyConstraint(
            ["latest_run_id"],
            ["processing_runs.id"],
            name=op.f("fk_recruitment_candidates_latest_run_id_processing_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_recruitment_candidates_created_by_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recruitment_candidates")),
        sa.UniqueConstraint("file_id", name="uq_recruitment_candidates_file_id"),
    )
    op.create_index(
        "ix_recruitment_candidates_project_status_created",
        "recruitment_candidates",
        ["project_id", "parse_status", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_recruitment_candidates_project_name",
        "recruitment_candidates",
        ["project_id", "display_name"],
        unique=False,
    )

    op.create_table(
        "candidate_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_version", sa.String(length=80), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("text_extraction_method", sa.String(length=20), nullable=False),
        sa.Column("highest_education_level", sa.String(length=30)),
        sa.Column("total_experience_months", sa.Integer()),
        sa.Column(
            "structured_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "text_extraction_method IN ('pdf_text','docx')",
            name=op.f("ck_candidate_profiles_text_extraction_method"),
        ),
        sa.CheckConstraint(
            "total_experience_months IS NULL OR total_experience_months >= 0",
            name=op.f("ck_candidate_profiles_experience_months"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(structured_payload) = 'object'",
            name=op.f("ck_candidate_profiles_structured_payload_object"),
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["recruitment_candidates.id"],
            name=op.f("fk_candidate_profiles_candidate_id_recruitment_candidates"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_run_id"],
            ["processing_runs.id"],
            name=op.f("fk_candidate_profiles_created_by_run_id_processing_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_profiles")),
        sa.UniqueConstraint("candidate_id", name="uq_candidate_profiles_candidate_id"),
    )

    op.create_table(
        "candidate_skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("capability_id", sa.Uuid()),
        sa.Column("raw_name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("proficiency", sa.String(length=20)),
        sa.Column("explicit_experience_months", sa.Integer()),
        sa.Column("evidence_strength", sa.String(length=20), nullable=False),
        sa.Column("evidence_quote", sa.Text(), nullable=False),
        sa.Column("evidence_start", sa.Integer(), nullable=False),
        sa.Column("evidence_end", sa.Integer(), nullable=False),
        sa.Column("mapping_method", sa.String(length=30), nullable=False),
        sa.Column("mapping_status", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "proficiency IS NULL OR "
            "proficiency IN ('beginner','intermediate','advanced')",
            name=op.f("ck_candidate_skills_proficiency"),
        ),
        sa.CheckConstraint(
            "explicit_experience_months IS NULL OR explicit_experience_months >= 0",
            name=op.f("ck_candidate_skills_experience_months"),
        ),
        sa.CheckConstraint(
            "evidence_strength IN ('mention','project','work')",
            name=op.f("ck_candidate_skills_evidence_strength"),
        ),
        sa.CheckConstraint(
            "mapping_method IN ('canonical_exact','alias_exact','unmapped')",
            name=op.f("ck_candidate_skills_mapping_method"),
        ),
        sa.CheckConstraint(
            "mapping_status IN ('mapped','unmapped')",
            name=op.f("ck_candidate_skills_mapping_status"),
        ),
        sa.CheckConstraint(
            "(mapping_status = 'mapped') = (capability_id IS NOT NULL)",
            name=op.f("ck_candidate_skills_mapping_target"),
        ),
        sa.CheckConstraint(
            "(mapping_status = 'mapped' AND mapping_method IN "
            "('canonical_exact','alias_exact')) OR "
            "(mapping_status = 'unmapped' AND mapping_method = 'unmapped')",
            name=op.f("ck_candidate_skills_mapping_combination"),
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1",
            name=op.f("ck_candidate_skills_confidence"),
        ),
        sa.CheckConstraint(
            "evidence_start >= 0 AND evidence_end > evidence_start",
            name=op.f("ck_candidate_skills_evidence_offsets"),
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["candidate_profiles.id"],
            name=op.f("fk_candidate_skills_profile_id_candidate_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["capability_id"],
            ["capabilities.id"],
            name=op.f("fk_candidate_skills_capability_id_capabilities"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_skills")),
        sa.UniqueConstraint(
            "profile_id", "normalized_name", name="uq_candidate_skills_name"
        ),
    )
    op.create_index(
        "ix_candidate_skills_mapping",
        "candidate_skills",
        ["profile_id", "mapping_status"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_skills_capability",
        "candidate_skills",
        ["capability_id"],
        unique=False,
        postgresql_where=sa.text("capability_id IS NOT NULL"),
    )
    op.create_index(
        "uq_candidate_skills_profile_capability",
        "candidate_skills",
        ["profile_id", "capability_id"],
        unique=True,
        postgresql_where=sa.text("capability_id IS NOT NULL"),
    )

    op.create_table(
        "recruitment_match_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("requirements_revision", sa.Integer(), nullable=False),
        sa.Column("requirements_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("candidate_selection_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("weight_version", sa.String(length=40), nullable=False),
        sa.Column(
            "weight_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "requirements_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "skipped_candidates",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("high_count", sa.Integer(), nullable=False),
        sa.Column("medium_count", sa.Integer(), nullable=False),
        sa.Column("low_count", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "requirements_revision >= 1",
            name=op.f("ck_recruitment_match_runs_requirements_revision"),
        ),
        sa.CheckConstraint(
            "result_count >= 1",
            name=op.f("ck_recruitment_match_runs_result_count"),
        ),
        sa.CheckConstraint(
            "skipped_count >= 0",
            name=op.f("ck_recruitment_match_runs_skipped_count"),
        ),
        sa.CheckConstraint(
            "high_count >= 0",
            name=op.f("ck_recruitment_match_runs_high_count"),
        ),
        sa.CheckConstraint(
            "medium_count >= 0",
            name=op.f("ck_recruitment_match_runs_medium_count"),
        ),
        sa.CheckConstraint(
            "low_count >= 0",
            name=op.f("ck_recruitment_match_runs_low_count"),
        ),
        sa.CheckConstraint(
            "high_count + medium_count + low_count = result_count",
            name=op.f("ck_recruitment_match_runs_level_counts"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(weight_snapshot) = 'object'",
            name=op.f("ck_recruitment_match_runs_weight_snapshot_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(requirements_snapshot) = 'object'",
            name=op.f("ck_recruitment_match_runs_requirements_snapshot_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(skipped_candidates) = 'array'",
            name=op.f("ck_recruitment_match_runs_skipped_candidates_array"),
        ),
        sa.CheckConstraint(
            "jsonb_array_length(skipped_candidates) = skipped_count",
            name=op.f("ck_recruitment_match_runs_skipped_candidates_count"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["recruitment_projects.id"],
            name=op.f("fk_recruitment_match_runs_project_id_recruitment_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_recruitment_match_runs_created_by_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recruitment_match_runs")),
        sa.UniqueConstraint(
            "project_id",
            "requirements_sha256",
            "candidate_selection_sha256",
            "weight_version",
            name="uq_recruitment_match_runs_inputs",
        ),
    )
    op.create_index(
        "ix_recruitment_match_runs_project_created",
        "recruitment_match_runs",
        ["project_id", sa.literal_column("created_at DESC")],
        unique=False,
    )

    op.create_table(
        "recruitment_match_results",
        sa.Column("match_run_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
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
            "candidate_snapshot",
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
            "rank >= 1",
            name=op.f("ck_recruitment_match_results_positive_rank"),
        ),
        sa.CheckConstraint(
            "total_score BETWEEN 0 AND 100",
            name=op.f("ck_recruitment_match_results_score_range"),
        ),
        sa.CheckConstraint(
            "match_level IN ('high','medium','low')",
            name=op.f("ck_recruitment_match_results_match_level"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(dimension_scores) = 'object'",
            name=op.f("ck_recruitment_match_results_dimension_scores_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(matched_capabilities) = 'array'",
            name=op.f("ck_recruitment_match_results_matched_capabilities_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(missing_capabilities) = 'array'",
            name=op.f("ck_recruitment_match_results_missing_capabilities_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(gap_summary) = 'object'",
            name=op.f("ck_recruitment_match_results_gap_summary_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(candidate_snapshot) = 'object'",
            name=op.f("ck_recruitment_match_results_candidate_snapshot_object"),
        ),
        sa.ForeignKeyConstraint(
            ["match_run_id"],
            ["recruitment_match_runs.id"],
            name=op.f(
                "fk_recruitment_match_results_match_run_id_recruitment_match_runs"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["recruitment_candidates.id"],
            name=op.f(
                "fk_recruitment_match_results_candidate_id_recruitment_candidates"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id"],
            ["candidate_profiles.id"],
            name=op.f(
                "fk_recruitment_match_results_candidate_profile_id_candidate_profiles"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "match_run_id",
            "candidate_id",
            name=op.f("pk_recruitment_match_results"),
        ),
        sa.UniqueConstraint(
            "match_run_id",
            "rank",
            name="uq_recruitment_match_results_run_rank",
        ),
    )


def downgrade() -> None:
    op.drop_table("recruitment_match_results")
    op.drop_index(
        "ix_recruitment_match_runs_project_created",
        table_name="recruitment_match_runs",
    )
    op.drop_table("recruitment_match_runs")
    op.drop_index(
        "uq_candidate_skills_profile_capability",
        table_name="candidate_skills",
    )
    op.drop_index("ix_candidate_skills_capability", table_name="candidate_skills")
    op.drop_index("ix_candidate_skills_mapping", table_name="candidate_skills")
    op.drop_table("candidate_skills")
    op.drop_table("candidate_profiles")
    op.drop_index(
        "ix_recruitment_candidates_project_name",
        table_name="recruitment_candidates",
    )
    op.drop_index(
        "ix_recruitment_candidates_project_status_created",
        table_name="recruitment_candidates",
    )
    op.drop_table("recruitment_candidates")
    op.drop_index(
        "ix_recruitment_projects_status_updated",
        table_name="recruitment_projects",
    )
    op.drop_index(
        "ix_recruitment_projects_owner_created",
        table_name="recruitment_projects",
    )
    op.drop_table("recruitment_projects")
