"""Add processing job ID to documents.

Revision ID: 0002_processing_job_id
Revises: 0001_existing_schema
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_processing_job_id"
down_revision: str | None = "0001_existing_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "processing_job_id",
            sa.String(),
            nullable=True,
        ),
    )

    op.add_column(
        "documents",
        sa.Column(
            "processing_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.add_column(
        "documents",
        sa.Column(
            "processing_claim_id",
            sa.String(),
            nullable=True,
        ),
    )

    op.add_column(
        "documents",
        sa.Column(
            "processing_lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "documents",
        "processing_lease_expires_at",
    )

    op.drop_column(
        "documents",
        "processing_claim_id",
    )

    op.drop_column(
        "documents",
        "processing_attempt_count",
    )

    op.drop_column(
        "documents",
        "processing_job_id",
    )
