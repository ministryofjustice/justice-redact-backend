"""Add document warning workflow state.

Revision ID: 0003_document_warning_state
Revises: 0002_processing_job_id
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_document_warning_state"
down_revision: str | None = "0002_processing_job_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "warning_reason",
            sa.String(),
            nullable=True,
        ),
    )

    op.add_column(
        "documents",
        sa.Column(
            "warning_acknowledged_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "documents",
        "warning_acknowledged_at",
    )

    op.drop_column(
        "documents",
        "warning_reason",
    )
