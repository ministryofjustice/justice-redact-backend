from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from app.models.document import Base


class ReviewResult(Base):
    __tablename__ = "review_results"

    document_id = Column(
        String,
        ForeignKey("documents.document_id"),
        primary_key=True,
    )

    review_json = Column(JSONB, nullable=False)
