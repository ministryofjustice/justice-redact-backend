from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.models.base import Base


class RedactionRun(Base):
    __tablename__ = "redaction_runs"

    run_id = Column(
        String,
        primary_key=True,
    )

    document_id = Column(
        String,
        ForeignKey("documents.document_id"),
        nullable=False,
        index=True,
    )

    review_revision = Column(
        Integer,
        nullable=False,
    )

    status = Column(
        String,
        nullable=False,
    )

    decisions_snapshot = Column(
        JSONB,
        nullable=False,
    )

    attempt_count = Column(
        Integer,
        nullable=False,
        default=0,
    )

    claim_id = Column(
        String,
        nullable=True,
    )

    lease_expires_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    page_counts = Column(
        JSONB,
        nullable=True,
    )

    error_message = Column(
        Text,
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    started_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancelled_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )
