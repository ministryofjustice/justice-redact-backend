from sqlalchemy import Column, DateTime, String, Text, Integer
from sqlalchemy.sql import func

from app.models.base import Base


class Document(Base):
    __tablename__ = "documents"

    document_id = Column(String, primary_key=True)
    filename = Column(String, nullable=False)
    status = Column(String, nullable=False)
    document_type = Column(String, nullable=False, default="unidentified")
    processing_job_id = Column(String, nullable=True)
    processing_attempt_count = Column(
        Integer,
        nullable=False,
        default=0,
    )
    processing_claim_id = Column(
        String,
        nullable=True,
    )
    processing_lease_expires_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    subject_name = Column(Text, nullable=False, default="")
    subject_prison_number = Column(Text, nullable=False, default="")
    other_phrases = Column(Text, nullable=False, default="")

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    processing_completed_at = Column(DateTime(timezone=True), nullable=True)

    redaction_started_at = Column(DateTime(timezone=True), nullable=True)
    redaction_completed_at = Column(DateTime(timezone=True), nullable=True)

    error_message = Column(Text, nullable=True)
