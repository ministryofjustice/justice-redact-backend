"""Persist the winning redaction export claim.

Revision ID: 0012
Revises: 0011_ready_notification_sent_at
"""

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = '0011_ready_notification_sent_at'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "redaction_runs",
        sa.Column(
            "published_claim_id",
            sa.String(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "redaction_runs",
        "published_claim_id",
    )
