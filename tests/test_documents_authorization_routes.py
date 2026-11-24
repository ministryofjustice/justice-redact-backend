import pytest
from fastapi import HTTPException

from app.api.routers import documents
from app.services.auth_service import AuthenticatedUser


CURRENT_USER = AuthenticatedUser(
    user_id="user-123",
    email="user@justice.gov.uk",
)


@pytest.mark.anyio
async def test_image_preview_authorizes_document_before_reading_s3(
    monkeypatch,
):
    def reject_document(
        document_id,
        user_id,
    ):
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        )

    monkeypatch.setattr(
        documents,
        "get_document_for_user_or_404",
        reject_document,
    )

    s3_called = False

    def fake_get_object_from_s3(key):
        nonlocal s3_called
        s3_called = True
        return b"image"

    monkeypatch.setattr(
        documents,
        "get_object_from_s3",
        fake_get_object_from_s3,
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        await documents.get_document_image_preview(
            "document-123",
            "image-123",
            current_user=CURRENT_USER,
        )

    assert exc_info.value.status_code == 404
    assert s3_called is False


@pytest.mark.anyio
async def test_image_preview_reads_s3_for_owned_document(
    monkeypatch,
):
    ownership_checks = []

    def allow_document(
        document_id,
        user_id,
    ):
        ownership_checks.append(
            (
                document_id,
                user_id,
            )
        )

        return {
            "documentId": document_id,
        }

    monkeypatch.setattr(
        documents,
        "get_document_for_user_or_404",
        allow_document,
    )

    monkeypatch.setattr(
        documents,
        "get_object_from_s3",
        lambda key: b"png-bytes",
    )

    response = (
        await documents
        .get_document_image_preview(
            "document-123",
            "image-123",
            current_user=CURRENT_USER,
        )
    )

    assert ownership_checks == [
        (
            "document-123",
            "user-123",
        )
    ]

    assert response.body == b"png-bytes"
    assert (
        response.media_type
        == "image/png"
    )


@pytest.mark.anyio
async def test_process_document_checks_ownership_before_queueing(
    monkeypatch,
):
    def reject_document(
        document_id,
        user_id,
    ):
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        )

    monkeypatch.setattr(
        documents,
        "get_document_for_user_or_404",
        reject_document,
    )

    queue_called = False

    def fake_send_message(
        *,
        document_id,
        job_id,
    ):
        nonlocal queue_called
        queue_called = True
        return "message-123"

    monkeypatch.setattr(
        documents,
        "send_document_processing_message",
        fake_send_message,
    )

    request = documents.ProcessDocumentRequest(
        subjectName="Test User",
        subjectPrisonNumber="A1234BC",
        otherPhrases="",
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        await documents.process_document(
            "document-123",
            request,
            current_user=CURRENT_USER,
        )

    assert exc_info.value.status_code == 404
    assert queue_called is False


def test_document_status_endpoint_requires_authentication():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(
        documents.router
    )

    client = TestClient(app)

    response = client.get(
        "/documents/document-123/status"
    )

    assert response.status_code == 401

    assert response.json() == {
        "detail": "Authentication required",
    }
