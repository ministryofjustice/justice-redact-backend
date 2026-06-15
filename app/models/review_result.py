from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class ReviewResult(Base):
    __tablename__ = "review_results"

    document_id = Column(
        String,
        ForeignKey("documents.document_id"),
        primary_key=True,
    )

    review_json = Column(JSONB, nullable=False)
