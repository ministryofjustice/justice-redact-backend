from fastapi import APIRouter, HTTPException

from app.services.document_store import get_document_or_404
from app.services.file_store import processed_review_path, read_json

router = APIRouter(prefix="/documents", tags=["review"])


@router.get("/{document_id}/review")
async def get_document_review(document_id: str):
    get_document_or_404(document_id)

    path = processed_review_path(document_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Processed review data not found")

    return read_json(path)
