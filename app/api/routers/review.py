from fastapi import APIRouter, HTTPException

from app.services.document_store import get_document_or_404
from app.services.review_result_store import get_review_result

router = APIRouter(prefix="/documents", tags=["review"])


@router.get("/{document_id}/review")
async def get_document_review(document_id: str):
    get_document_or_404(document_id)

    review_result = get_review_result(document_id)

    if review_result is None:
        raise HTTPException(
            status_code=404,
            detail="Processed review data not found",
        )

    return review_result
