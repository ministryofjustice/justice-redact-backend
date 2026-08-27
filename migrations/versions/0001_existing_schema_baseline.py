"""Baseline the existing Justice Redact schema.

Revision ID: 0001_existing_schema
Revises:
"""
from collections.abc import Sequence

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_existing_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = {"documents", "review_results", "redaction_decisions"}


def upgrade() -> None:
    existing_application_tables: set[str] = set()
    if not context.is_offline_mode():
        existing_tables = set(
            sa.inspect(op.get_bind()).get_table_names(schema="public")
        )
        existing_application_tables = existing_tables & TABLES

    if existing_application_tables == TABLES:
        # Existing environments already have this schema. Alembic records this
        # revision after the migration returns, without recreating the tables.
        return

    if existing_application_tables:
        missing = ", ".join(sorted(TABLES - existing_application_tables))
        present = ", ".join(sorted(existing_application_tables))
        raise RuntimeError(
            "Cannot baseline a partial Justice Redact schema. "
            f"Present: {present}. Missing: {missing}."
        )

    op.create_table(
        "documents",
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("subject_name", sa.Text(), nullable=False),
        sa.Column("subject_prison_number", sa.Text(), nullable=False),
        sa.Column("other_phrases", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processing_started_at", sa.DateTime(timezone=True)),
        sa.Column("processing_completed_at", sa.DateTime(timezone=True)),
        sa.Column("redaction_started_at", sa.DateTime(timezone=True)),
        sa.Column("redaction_completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.PrimaryKeyConstraint("document_id", name="documents_pkey"),
    )

    op.create_table(
        "review_results",
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("review_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.document_id"],
            name="review_results_document_id_fkey",
        ),
        sa.PrimaryKeyConstraint("document_id", name="review_results_pkey"),
    )

    op.create_table(
        "redaction_decisions",
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column(
            "decisions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.document_id"],
            name="redaction_decisions_document_id_fkey",
        ),
        sa.PrimaryKeyConstraint("document_id", name="redaction_decisions_pkey"),
    )


def downgrade() -> None:
    op.drop_table("redaction_decisions")
    op.drop_table("review_results")
    op.drop_table("documents")
