from app.core.database import SessionLocal
from app.models.review_result import ReviewResult


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
