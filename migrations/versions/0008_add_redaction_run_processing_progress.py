"""Add redaction run processing progress.

Revision ID: 0008_redaction_run_processing_progress
Revises: 0007_processing_progress
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision = "0008_redaction_run_progress"
down_revision: str | None = "0007_processing_progress"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "redaction_runs",
        sa.Column(
            "processing_progress",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.create_check_constraint(
        "ck_redaction_runs_processing_progress_range",
        "redaction_runs",
        "processing_progress >= 0 AND processing_progress <= 100",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_redaction_runs_processing_progress_range",
        "redaction_runs",
        type_="check",
    )

    op.drop_column(
        "redaction_runs",
        "processing_progress",
    )
