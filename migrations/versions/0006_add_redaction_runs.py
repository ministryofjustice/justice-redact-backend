"""Add versioned redaction runs.

Revision ID: 0006_redaction_runs
Revises: 0005_redaction_decision_revision
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0006_redaction_runs"
down_revision: str | None = "0005_redaction_decision_revision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "redaction_runs",
        sa.Column(
            "run_id",
            sa.String(),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.String(),
            nullable=False,
        ),
        sa.Column(
            "review_revision",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
        ),
        sa.Column(
            "decisions_snapshot",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "claim_id",
            sa.String(),
            nullable=True,
        ),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "page_counts",
            postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "cancelled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.document_id"],
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )

    op.create_index(
        "ix_redaction_runs_document_id",
        "redaction_runs",
        ["document_id"],
        unique=False,
    )

    op.add_column(
        "documents",
        sa.Column(
            "current_redaction_run_id",
            sa.String(),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "fk_documents_current_redaction_run_id",
        "documents",
        "redaction_runs",
        ["current_redaction_run_id"],
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_documents_current_redaction_run_id",
        "documents",
        type_="foreignkey",
    )

    op.drop_column(
        "documents",
        "current_redaction_run_id",
    )

    op.drop_index(
        "ix_redaction_runs_document_id",
        table_name="redaction_runs",
    )

    op.drop_table("redaction_runs")
