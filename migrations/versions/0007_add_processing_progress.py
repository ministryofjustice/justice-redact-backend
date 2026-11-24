"""Add document processing progress.

Revision ID: 0007_processing_progress
Revises: 0006_redaction_runs
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0007_processing_progress"
down_revision: str | None = "0006_redaction_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "processing_progress",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.create_check_constraint(
        "ck_documents_processing_progress_range",
        "documents",
        "processing_progress >= 0 AND processing_progress <= 100",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_documents_processing_progress_range",
        "documents",
        type_="check",
    )

    op.drop_column(
        "documents",
        "processing_progress",
    )
