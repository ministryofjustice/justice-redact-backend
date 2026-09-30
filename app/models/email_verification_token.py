from sqlalchemy import (
    Column,
    DateTime,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.models.base import Base


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    __table_args__ = (
        UniqueConstraint(
            "token_hash",
            name="uq_email_verification_tokens_token_hash",
        ),
    )

    verification_id = Column(
        String,
        primary_key=True,
    )

    email = Column(
        String,
        nullable=False,
        index=True,
    )

    token_hash = Column(
        String(64),
        nullable=False,
    )

    browser_token_hash = Column(
        String(64),
        nullable=False,
    )

    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    consumed_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
