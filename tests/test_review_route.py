import pytest
from fastapi import HTTPException

from app.api.routers import review
from app.services.auth_service import AuthenticatedUser


CURRENT_USER = AuthenticatedUser(
    user_id="user-123",
    email="user@justice.gov.uk",
)


def _document():
    return {
        "documentId": "document-123",
        "status": "ready_for_review",
    }


@pytest.mark.anyio
async def test_get_document_review_returns_lightweight_review_result(
    monkeypatch,
):
    monkeypatch.setattr(
        review,
        "get_document_for_user_or_404",
        lambda document_id, user_id: _document(),
    )

    review_result = {
        "documentId": "document-123",
        "filename": "example.pdf",
        "status": "ready_for_review",
        "pages": [],
        "findings": [
            {
                "id": "finding_000001",
            }
        ],
        "summary": {
            "totalPages": 1109,
            "totalFindings": 1,
        },
        "subjectDetails": {
            "subjectName": "",
            "subjectPrisonNumber": "",
            "otherPhrases": [],
        },
    }

    monkeypatch.setattr(
        review,
        "get_review_result",
        lambda document_id: review_result,
    )

    response = await review.get_document_review(
        "document-123",
        current_user=CURRENT_USER,
    )

    assert response == review_result
    assert response["pages"] == []


@pytest.mark.anyio
async def test_get_document_review_pages_returns_requested_pages(
    monkeypatch,
):
    monkeypatch.setattr(
        review,
        "get_document_for_user_or_404",
        lambda document_id, user_id: _document(),
    )

    page_calls = []

    def fake_get_review_pages(
        *,
        document_id,
        page_start,
        page_end,
    ):
        page_calls.append(
            (
                document_id,
                page_start,
                page_end,
            )
        )

        return [
            {"pageNumber": 51},
            {"pageNumber": 100},
        ]

    monkeypatch.setattr(
        review,
        "get_review_pages",
        fake_get_review_pages,
    )

    response = await review.get_document_review_pages(
        "document-123",
        page_start=51,
        page_end=100,
        current_user=CURRENT_USER,
    )

    assert page_calls == [
        (
            "document-123",
            51,
            100,
        )
    ]

    assert response == {
        "pageStart": 51,
        "pageEnd": 100,
        "pages": [
            {"pageNumber": 51},
            {"pageNumber": 100},
        ],
    }


@pytest.mark.anyio
async def test_get_document_review_pages_rejects_more_than_50_pages(
    monkeypatch,
):
    monkeypatch.setattr(
        review,
        "get_document_for_user_or_404",
        lambda document_id, user_id: _document(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await review.get_document_review_pages(
            "document-123",
            page_start=1,
            page_end=51,
            current_user=CURRENT_USER,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == ("A maximum of 50 pages can be requested at once")


@pytest.mark.anyio
async def test_get_document_review_pages_rejects_reversed_range(
    monkeypatch,
):
    monkeypatch.setattr(
        review,
        "get_document_for_user_or_404",
        lambda document_id, user_id: _document(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await review.get_document_review_pages(
            "document-123",
            page_start=100,
            page_end=51,
            current_user=CURRENT_USER,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == (
        "pageEnd must be greater than or equal to pageStart"
    )


@pytest.mark.anyio
async def test_get_document_review_search_returns_compact_pages(
    monkeypatch,
):
    monkeypatch.setattr(
        review,
        "get_document_for_user_or_404",
        lambda document_id, user_id: _document(),
    )

    search_calls = []

    def fake_get_review_search_pages(
        *,
        document_id,
    ):
        search_calls.append(document_id)

        return [
            {
                "pageNumber": 1,
                "textItems": [
                    {
                        "itemId": "item-1",
                        "text": "example",
                    }
                ],
                "tables": [],
                "images": [],
            }
        ]

    monkeypatch.setattr(
        review,
        "get_review_search_pages",
        fake_get_review_search_pages,
    )

    response = await review.get_document_review_search(
        "document-123",
        current_user=CURRENT_USER,
    )

    assert search_calls == ["document-123"]

    assert response == {
        "pages": [
            {
                "pageNumber": 1,
                "textItems": [
                    {
                        "itemId": "item-1",
                        "text": "example",
                    }
                ],
                "tables": [],
                "images": [],
            }
        ]
    }


@pytest.mark.anyio
async def test_document_review_checks_ownership_before_loading_review_data(
    monkeypatch,
):
    def reject_document(
        document_id,
        user_id,
    ):
        raise review.HTTPException(
            status_code=404,
            detail="Document not found",
        )

    monkeypatch.setattr(
        review,
        "get_document_for_user_or_404",
        reject_document,
    )

    review_data_called = False

    def fake_get_review_result(document_id):
        nonlocal review_data_called
        review_data_called = True
        return {}

    monkeypatch.setattr(
        review,
        "get_review_result",
        fake_get_review_result,
    )

    with pytest.raises(review.HTTPException) as exc_info:
        await review.get_document_review(
            "document-123",
            current_user=CURRENT_USER,
        )

    assert exc_info.value.status_code == 404
    assert review_data_called is False
