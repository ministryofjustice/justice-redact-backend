import pytest

from app.api.routers import documents
from app.services.auth_service import AuthenticatedUser


CURRENT_USER = AuthenticatedUser(
    user_id="user-123",
    email="user@justice.gov.uk",
)


@pytest.mark.anyio
async def test_get_document_workflow_returns_authoritative_navigation(monkeypatch):
    monkeypatch.setattr(
        documents,
        "get_document_for_user_or_404",
        lambda document_id, user_id: {
            "documentId": document_id,
            "status": "ready_for_review",
            "warningReason": None,
            "warningAcknowledgedAt": None,
        },
    )

    response = await documents.get_document_workflow(
        "document-123",
        current_user=CURRENT_USER,
    )

    assert response == {
        "documentId": "document-123",
        "status": "ready_for_review",
        "currentRedactionRunId": None,
        "preferredPage": "review",
        "allowedPages": ["review"],
    }


@pytest.mark.anyio
async def test_acknowledge_document_warning_persists_acknowledgement(monkeypatch):
    document = {
        "documentId": "document-123",
        "status": "uploaded",
        "warningReason": "scanned",
        "warningAcknowledgedAt": None,
    }

    monkeypatch.setattr(
        documents,
        "get_document_for_user_or_404",
        lambda document_id, _user_id: document,
    )

    update_calls = []

    def fake_update_document_record(document_id, **updates):
        update_calls.append((document_id, updates))

    monkeypatch.setattr(
        documents,
        "update_document_record",
        fake_update_document_record,
    )

    response = await documents.acknowledge_document_warning(
        "document-123",
        current_user=CURRENT_USER,
    )

    assert len(update_calls) == 1

    document_id, updates = update_calls[0]

    assert document_id == "document-123"
    assert updates["warning_acknowledged_at"] is not None

    assert response["documentId"] == "document-123"
    assert response["status"] == "uploaded"
    assert response["preferredPage"] == "subject-details"
    assert response["allowedPages"] == ["subject-details"]

    assert response["currentRedactionRunId"] is None


@pytest.mark.anyio
async def test_abandon_document_invalidates_processing_and_returns_upload_workflow(
    monkeypatch,
):
    monkeypatch.setattr(
        documents,
        "get_document_for_user_or_404",
        lambda document_id, user_id: {
            "documentId": document_id,
            "status": "processing",
            "warningReason": None,
            "warningAcknowledgedAt": None,
        },
    )

    abandon_calls = []

    def fake_try_abandon_document_processing(*, document_id):
        abandon_calls.append(document_id)
        return True

    monkeypatch.setattr(
        documents,
        "try_abandon_document_processing",
        fake_try_abandon_document_processing,
        raising=False,
    )

    monkeypatch.setattr(
        documents,
        "delete_s3_prefix",
        lambda prefix: None,
    )

    response = await documents.abandon_document(
        "document-123",
        current_user=CURRENT_USER,
    )

    assert abandon_calls == ["document-123"]

    assert response == {
        "documentId": "document-123",
        "status": "abandoned",
        "currentRedactionRunId": None,
        "preferredPage": "upload",
        "allowedPages": ["upload"],
    }


@pytest.mark.anyio
async def test_abandon_document_deletes_document_s3_prefix_after_invalidation(
    monkeypatch,
):
    monkeypatch.setattr(
        documents,
        "get_document_for_user_or_404",
        lambda document_id, user_id: {
            "documentId": document_id,
            "status": "processing",
            "warningReason": None,
            "warningAcknowledgedAt": None,
        },
    )

    monkeypatch.setattr(
        documents,
        "try_abandon_document_processing",
        lambda *, document_id: True,
    )

    deleted_prefixes = []

    monkeypatch.setattr(
        documents,
        "delete_s3_prefix",
        lambda prefix: deleted_prefixes.append(prefix),
        raising=False,
    )

    response = await documents.abandon_document(
        "document-123",
        current_user=CURRENT_USER,
    )

    assert deleted_prefixes == [
        "documents/document-123/",
    ]

    assert response["status"] == "abandoned"


@pytest.mark.anyio
async def test_abandon_document_still_succeeds_when_s3_cleanup_fails(
    monkeypatch,
):
    monkeypatch.setattr(
        documents,
        "get_document_for_user_or_404",
        lambda document_id, user_id: {
            "documentId": document_id,
            "status": "processing",
            "warningReason": None,
            "warningAcknowledgedAt": None,
        },
    )

    monkeypatch.setattr(
        documents,
        "try_abandon_document_processing",
        lambda *, document_id: True,
    )

    def fail_cleanup(prefix):
        raise RuntimeError("S3 unavailable")

    monkeypatch.setattr(
        documents,
        "delete_s3_prefix",
        fail_cleanup,
    )

    response = await documents.abandon_document(
        "document-123",
        current_user=CURRENT_USER,
    )

    assert response == {
        "documentId": "document-123",
        "status": "abandoned",
        "currentRedactionRunId": None,
        "preferredPage": "upload",
        "allowedPages": ["upload"],
    }


@pytest.mark.anyio
async def test_get_document_status_returns_processing_progress(
    monkeypatch,
):
    monkeypatch.setattr(
        documents,
        "get_document_for_user_or_404",
        lambda document_id, user_id: {
            "documentId": document_id,
            "filename": "test.pdf",
            "status": "processing",
            "processingProgress": 57,
        },
    )

    response = await documents.get_document_status(
        "document-123",
        current_user=CURRENT_USER,
    )

    assert response == {
        "documentId": "document-123",
        "filename": "test.pdf",
        "status": "processing",
        "processingProgress": 57,
    }


@pytest.mark.anyio
async def test_return_to_subject_details_preserves_document(
    monkeypatch,
):
    from app.services.auth_service import AuthenticatedUser

    user = AuthenticatedUser(
        user_id="user-123",
        email="user@justice.gov.uk",
    )

    state = {"status": "processing"}
    cancellation_calls = []

    def get_owned_document(document_id, user_id):
        assert user_id == "user-123"
        return {
            "documentId": document_id,
            "status": state["status"],
        }

    def cancel_processing(*, document_id):
        cancellation_calls.append(document_id)
        state["status"] = "uploaded"
        return "subject-details"

    monkeypatch.setattr(
        documents,
        "get_document_for_user_or_404",
        get_owned_document,
    )
    monkeypatch.setattr(
        documents,
        "request_processing_return_to_subject_details",
        cancel_processing,
    )

    def unexpected_s3_delete(prefix):
        pytest.fail("Returning to Subject details must not delete S3 files")

    monkeypatch.setattr(
        documents,
        "delete_s3_prefix",
        unexpected_s3_delete,
    )

    result = await documents.return_to_subject_details(
        "document-123",
        current_user=user,
    )

    assert cancellation_calls == ["document-123"]
    assert result["status"] == "uploaded"
    assert result["preferredPage"] == "subject-details"


@pytest.mark.anyio
async def test_return_to_subject_details_preserves_completed_review(
    monkeypatch,
):
    from app.services.auth_service import AuthenticatedUser

    user = AuthenticatedUser(
        user_id="user-123",
        email="user@justice.gov.uk",
    )

    monkeypatch.setattr(
        documents,
        "get_document_for_user_or_404",
        lambda document_id, user_id: {
            "documentId": document_id,
            "status": "ready_for_review",
        },
    )

    monkeypatch.setattr(
        documents,
        "request_processing_return_to_subject_details",
        lambda *, document_id: "review",
    )

    result = await documents.return_to_subject_details(
        "document-123",
        current_user=user,
    )

    assert result["status"] == "ready_for_review"
    assert result["preferredPage"] == "review"


@pytest.mark.anyio
async def test_return_to_subject_details_rejects_unauthorized_user(
    monkeypatch,
):
    from fastapi import HTTPException
    from app.services.auth_service import AuthenticatedUser

    user = AuthenticatedUser(
        user_id="other-user",
        email="other@justice.gov.uk",
    )

    def reject_document(document_id, user_id):
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        )

    monkeypatch.setattr(
        documents,
        "get_document_for_user_or_404",
        reject_document,
    )

    def unexpected_cancellation(*, document_id):
        pytest.fail("Unauthorized user must not cancel processing")

    monkeypatch.setattr(
        documents,
        "request_processing_return_to_subject_details",
        unexpected_cancellation,
    )

    with pytest.raises(HTTPException) as exc_info:
        await documents.return_to_subject_details(
            "document-123",
            current_user=user,
        )

    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_return_to_subject_details_rejects_conflicting_state(
    monkeypatch,
):
    from fastapi import HTTPException
    from app.services.auth_service import AuthenticatedUser

    user = AuthenticatedUser(
        user_id="user-123",
        email="user@justice.gov.uk",
    )

    monkeypatch.setattr(
        documents,
        "get_document_for_user_or_404",
        lambda document_id, user_id: {
            "documentId": document_id,
            "status": "applying_redactions",
        },
    )

    monkeypatch.setattr(
        documents,
        "request_processing_return_to_subject_details",
        lambda *, document_id: "conflict",
    )

    with pytest.raises(HTTPException) as exc_info:
        await documents.return_to_subject_details(
            "document-123",
            current_user=user,
        )

    assert exc_info.value.status_code == 409
