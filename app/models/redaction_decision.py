from sqlalchemy import Column, ForeignKey, String
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
