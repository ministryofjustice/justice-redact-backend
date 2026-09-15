from fastapi import APIRouter, HTTPException, Query

from app.logging_config import logger
from app.services.document_store import get_document_or_404
from app.services.review_data_service import (
    get_review_pages,
    get_review_search_pages,
)
from app.services.review_result_store import get_review_result


router = APIRouter(prefix="/documents", tags=["review"])

MAX_REVIEW_PAGE_RANGE = 50


@router.get("/{document_id}/review")
async def get_document_review(document_id: str):
    get_document_or_404(document_id)

    review_result = get_review_result(document_id)

    if review_result is None:
        logger.warning(
            "document_review_not_found",
            extra={
                "event": "document_review_not_found",
                "document_id": document_id,
            },
        )
        raise HTTPException(
            status_code=404,
            detail="Processed review data not found",
        )

    return review_result


@router.get("/{document_id}/review/pages")
async def get_document_review_pages(
    document_id: str,
    page_start: int = Query(
        ...,
        alias="pageStart",
        ge=1,
    ),
    page_end: int = Query(
        ...,
        alias="pageEnd",
        ge=1,
    ),
):
    get_document_or_404(document_id)

    if page_end < page_start:
        raise HTTPException(
            status_code=400,
            detail="pageEnd must be greater than or equal to pageStart",
        )

    requested_page_count = page_end - page_start + 1

    if requested_page_count > MAX_REVIEW_PAGE_RANGE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"A maximum of "
                f"{MAX_REVIEW_PAGE_RANGE} pages "
                f"can be requested at once"
            ),
        )

    pages = get_review_pages(
        document_id=document_id,
        page_start=page_start,
        page_end=page_end,
    )

    return {
        "pageStart": page_start,
        "pageEnd": page_end,
        "pages": pages,
    }


@router.get("/{document_id}/review/search")
async def get_document_review_search(
    document_id: str,
):
    get_document_or_404(document_id)

    pages = get_review_search_pages(
        document_id=document_id,
    )

    return {
        "pages": pages,
    }
