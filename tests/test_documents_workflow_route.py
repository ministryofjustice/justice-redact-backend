import pytest

from app.api.routers import documents


@pytest.mark.anyio
async def test_get_document_workflow_returns_authoritative_navigation(monkeypatch):
    monkeypatch.setattr(
        documents,
        "get_document_or_404",
        lambda document_id: {
            "documentId": document_id,
            "status": "ready_for_review",
            "warningReason": None,
            "warningAcknowledgedAt": None,
        },
    )

    response = await documents.get_document_workflow("document-123")

    assert response == {
        "documentId": "document-123",
        "status": "ready_for_review",
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
        "get_document_or_404",
        lambda document_id: document,
    )

    update_calls = []

    def fake_update_document_record(document_id, **updates):
        update_calls.append((document_id, updates))

    monkeypatch.setattr(
        documents,
        "update_document_record",
        fake_update_document_record,
    )

    response = await documents.acknowledge_document_warning("document-123")

    assert len(update_calls) == 1

    document_id, updates = update_calls[0]

    assert document_id == "document-123"
    assert updates["warning_acknowledged_at"] is not None

    assert response["documentId"] == "document-123"
    assert response["status"] == "uploaded"
    assert response["preferredPage"] == "subject-details"
    assert response["allowedPages"] == ["subject-details"]


@pytest.mark.anyio
async def test_abandon_document_invalidates_processing_and_returns_upload_workflow(
    monkeypatch,
):
    monkeypatch.setattr(
        documents,
        "get_document_or_404",
        lambda document_id: {
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

    response = await documents.abandon_document("document-123")

    assert abandon_calls == ["document-123"]

    assert response == {
        "documentId": "document-123",
        "status": "abandoned",
        "preferredPage": "upload",
        "allowedPages": ["upload"],
    }


@pytest.mark.anyio
async def test_abandon_document_deletes_document_s3_prefix_after_invalidation(
    monkeypatch,
):
    monkeypatch.setattr(
        documents,
        "get_document_or_404",
        lambda document_id: {
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

    response = await documents.abandon_document("document-123")

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
        "get_document_or_404",
        lambda document_id: {
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

    response = await documents.abandon_document("document-123")

    assert response == {
        "documentId": "document-123",
        "status": "abandoned",
        "preferredPage": "upload",
        "allowedPages": ["upload"],
    }
