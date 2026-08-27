"""Add document abandonment state.

Revision ID: 0004_document_abandoned_at
Revises: 0003_document_warning_state
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_document_abandoned_at"
down_revision: str | None = "0003_document_warning_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "abandoned_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "documents",
        "abandoned_at",
    )
