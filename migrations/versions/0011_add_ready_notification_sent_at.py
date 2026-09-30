"""Add document ready notification timestamp.

Revision ID: 0011_ready_notification_sent_at
Revises: 0010_email_verification_email
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0011_ready_notification_sent_at"
down_revision: str | None = "0010_email_verification_email"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "ready_notification_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "documents",
        "ready_notification_sent_at",
    )
