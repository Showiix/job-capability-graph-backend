"""allow local OCR extraction for resume images

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_resume_profiles_extraction_method"),
        "resume_profiles",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_resume_profiles_extraction_method"),
        "resume_profiles",
        "text_extraction_method IN ('pdf_text','docx','image_llm','image_ocr')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_resume_profiles_extraction_method"),
        "resume_profiles",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_resume_profiles_extraction_method"),
        "resume_profiles",
        "text_extraction_method IN ('pdf_text','docx','image_llm')",
    )
