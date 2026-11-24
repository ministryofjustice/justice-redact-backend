"""Make email verification challenges email based.

Revision ID: 0010_email_verification_email
Revises: 0009_user_auth
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0010_email_verification_email"
down_revision: str | None = "0009_user_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add the email first as nullable so existing verification challenges
    # can be backfilled from their current user relationship.
    op.add_column(
        "email_verification_tokens",
        sa.Column(
            "email",
            sa.String(),
            nullable=True,
        ),
    )

    op.execute(
        sa.text(
            """
            UPDATE email_verification_tokens
            SET email = users.email
            FROM users
            WHERE email_verification_tokens.user_id = users.user_id
            """
        )
    )

    op.alter_column(
        "email_verification_tokens",
        "email",
        existing_type=sa.String(),
        nullable=False,
    )

    op.create_index(
        "ix_email_verification_tokens_email",
        "email_verification_tokens",
        ["email"],
        unique=False,
    )

    op.drop_index(
        "ix_email_verification_tokens_user_id",
        table_name="email_verification_tokens",
    )

    op.drop_constraint(
        "email_verification_tokens_user_id_fkey",
        "email_verification_tokens",
        type_="foreignkey",
    )

    op.drop_column(
        "email_verification_tokens",
        "user_id",
    )


def downgrade() -> None:
    # Restore the previous user relationship.
    op.add_column(
        "email_verification_tokens",
        sa.Column(
            "user_id",
            sa.String(),
            nullable=True,
        ),
    )

    op.execute(
        sa.text(
            """
            UPDATE email_verification_tokens
            SET user_id = users.user_id
            FROM users
            WHERE email_verification_tokens.email = users.email
            """
        )
    )

    # Under the new model, a verification challenge may legitimately belong
    # to an email which is not in the Private Beta users table. Those
    # short-lived challenges cannot be represented by the previous schema,
    # so discard them if this migration is rolled back.
    op.execute(
        sa.text(
            """
            DELETE FROM email_verification_tokens
            WHERE user_id IS NULL
            """
        )
    )

    op.alter_column(
        "email_verification_tokens",
        "user_id",
        existing_type=sa.String(),
        nullable=False,
    )

    op.create_foreign_key(
        "email_verification_tokens_user_id_fkey",
        "email_verification_tokens",
        "users",
        ["user_id"],
        ["user_id"],
        ondelete="CASCADE",
    )

    op.create_index(
        "ix_email_verification_tokens_user_id",
        "email_verification_tokens",
        ["user_id"],
        unique=False,
    )

    op.drop_index(
        "ix_email_verification_tokens_email",
        table_name="email_verification_tokens",
    )

    op.drop_column(
        "email_verification_tokens",
        "email",
    )
