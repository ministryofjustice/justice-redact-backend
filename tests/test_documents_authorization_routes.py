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
        "get_review_result",
        lambda document_id: {
            "documentId": document_id,
        },
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


@pytest.mark.anyio
async def test_image_preview_uses_published_processing_job(
    monkeypatch,
):
    document_id = "document-123"
    job_id = "job-456"
    image_id = "image-123"

    monkeypatch.setattr(
        documents,
        "get_document_for_user_or_404",
        lambda document_id, user_id: {
            "documentId": document_id,
        },
    )

    monkeypatch.setattr(
        documents,
        "get_review_result",
        lambda document_id: {
            "documentId": document_id,
            "processingAssets": {
                "layout": "job",
                "jobId": job_id,
            },
        },
    )

    requested_keys = []

    def fake_get_object_from_s3(key):
        requested_keys.append(key)
        return b"png-bytes"

    monkeypatch.setattr(
        documents,
        "get_object_from_s3",
        fake_get_object_from_s3,
    )

    response = await documents.get_document_image_preview(
        document_id,
        image_id,
        current_user=CURRENT_USER,
    )

    assert requested_keys == [
        "documents/document-123/"
        "processing-jobs/job-456/"
        "previews/image-123.png"
    ]

    assert response.body == b"png-bytes"
    assert response.media_type == "image/png"


@pytest.mark.anyio
@pytest.mark.parametrize("enqueue_fails", [False, True])
async def test_processing_enqueue_cannot_override_cancelled_document(
    monkeypatch,
    enqueue_fails,
):
    from types import SimpleNamespace

    document_id = "document-123"

    # The initial request starts successfully, but the user
    # cancels processing before SQS enqueue finishes.
    monkeypatch.setattr(
        documents,
        "get_document_for_user_or_404",
        lambda document_id, user_id: {
            "documentId": document_id,
            "status": "uploaded",
        },
    )

    monkeypatch.setattr(
        documents,
        "try_start_document_processing_enqueue",
        lambda **kwargs: True,
    )

    def send_message(**kwargs):
        if enqueue_fails:
            raise RuntimeError("SQS enqueue failed")
        return "message-123"

    monkeypatch.setattr(
        documents,
        "send_document_processing_message",
        send_message,
    )

    # The cancellation invalidated the original job, so
    # neither transition may update the document.
    monkeypatch.setattr(
        documents,
        "mark_document_processing_queued",
        lambda **kwargs: False,
    )

    monkeypatch.setattr(
        documents,
        "mark_document_processing_enqueue_failed",
        lambda **kwargs: False,
    )

    response = await documents.process_document(
        document_id,
        SimpleNamespace(
            subjectName="Test Subject",
            subjectPrisonNumber="A1234BC",
            otherPhrases="",
        ),
        current_user=CURRENT_USER,
    )

    assert response == {
        "documentId": document_id,
        "status": "uploaded",
    }
