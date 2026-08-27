from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import Base


class RedactionDecision(Base):
    __tablename__ = "redaction_decisions"

    document_id = Column(
        String,
        ForeignKey("documents.document_id"),
        primary_key=True,
    )

    decisions_json = Column(JSONB, nullable=False)

    revision = Column(
        Integer,
        nullable=False,
        default=0,
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
    )
