"""expand graph change candidate types

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_graph_change_candidates_change_type"),
        "graph_change_candidates",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_graph_change_candidates_change_type"),
        "graph_change_candidates",
        "change_type IN ('create_job_role','skill_added','ai_skill_added',"
        "'skill_declining','weight_increased','weight_decreased',"
        "'promoted_to_required','demoted_to_bonus','skill_obsoleted')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_graph_change_candidates_change_type"),
        "graph_change_candidates",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_graph_change_candidates_change_type"),
        "graph_change_candidates",
        "change_type = 'create_job_role'",
    )
