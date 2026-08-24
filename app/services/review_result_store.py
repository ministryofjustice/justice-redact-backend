from sqlalchemy import select
from datetime import datetime
from app.core.database import SessionLocal
from app.models.review_result import ReviewResult
from app.models.document import Document


def upsert_review_result(document_id: str, review_json: dict) -> None:
    with SessionLocal() as session:
        review_result = session.get(ReviewResult, document_id)

        if review_result is None:
            review_result = ReviewResult(
                document_id=document_id,
                review_json=review_json,
            )
            session.add(review_result)
        else:
            review_result.review_json = review_json

        session.commit()


def publish_review_result_if_processing_owner(
    *,
    document_id: str,
    job_id: str,
    claim_id: str,
    review_json: dict,
    completed_at: datetime,
) -> bool:
    with SessionLocal() as session:
        document = session.execute(
            select(Document)
            .where(
                Document.document_id == document_id,
                Document.status == "processing",
                Document.processing_job_id == job_id,
                Document.processing_claim_id == claim_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if document is None:
            return False

        review_result = session.get(
            ReviewResult,
            document_id,
        )

        if review_result is None:
            review_result = ReviewResult(
                document_id=document_id,
                review_json=review_json,
            )
            session.add(review_result)
        else:
            review_result.review_json = review_json

        document.status = "ready_for_review"
        document.processing_completed_at = completed_at
        document.processing_claim_id = None
        document.processing_lease_expires_at = None
        document.error_message = None

        session.commit()

        return True


def get_review_result(document_id: str) -> dict | None:
    with SessionLocal() as session:
        review_result = session.get(ReviewResult, document_id)

        if review_result is None:
            return None

        return review_result.review_json
