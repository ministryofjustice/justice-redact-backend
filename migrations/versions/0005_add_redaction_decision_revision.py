"""Add redaction decision revision tracking.

Revision ID: 0005_redaction_decision_revision
Revises: 0004_document_abandoned_at
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_redaction_decision_revision"
down_revision: str | None = "0004_document_abandoned_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "redaction_decisions",
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.add_column(
        "redaction_decisions",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "redaction_decisions",
        "updated_at",
    )

    op.drop_column(
        "redaction_decisions",
        "revision",
    )
