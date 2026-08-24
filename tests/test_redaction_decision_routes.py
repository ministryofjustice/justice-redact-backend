import pytest
from fastapi import HTTPException

from app.api.routers import redactions
from app.models.redaction_models import (
    ApplyRedactionsRequest,
    SaveRedactionDecisionsRequest,
)


@pytest.mark.anyio
async def test_get_redaction_decisions_returns_revision_state(
    monkeypatch,
):
    monkeypatch.setattr(
        redactions,
        "get_document_or_404",
        lambda document_id: {"documentId": document_id},
    )

    monkeypatch.setattr(
        redactions,
        "get_redaction_decision_state",
        lambda document_id: {
            "documentId": document_id,
            "revision": 4,
            "decisions": [],
            "updatedAt": "2026-08-19T12:00:00+00:00",
        },
        raising=False,
    )

    response = await redactions.get_document_redaction_decisions("document-123")

    assert response == {
        "documentId": "document-123",
        "revision": 4,
        "decisions": [],
        "updatedAt": "2026-08-19T12:00:00+00:00",
    }


@pytest.mark.anyio
async def test_save_redaction_decisions_returns_new_revision(
    monkeypatch,
):
    monkeypatch.setattr(
        redactions,
        "get_document_or_404",
        lambda document_id: {"documentId": document_id},
    )

    monkeypatch.setattr(
        redactions,
        "save_redaction_decisions",
        lambda **kwargs: {
            "saved": True,
            "revision": 5,
        },
        raising=False,
    )

    request = SaveRedactionDecisionsRequest(
        documentId="document-123",
        decisions=[],
        expectedRevision=4,
    )

    response = await redactions.save_document_redaction_decisions(
        "document-123",
        request,
    )

    assert response == {
        "documentId": "document-123",
        "status": "saved",
        "revision": 5,
    }


@pytest.mark.anyio
async def test_save_redaction_decisions_rejects_stale_revision(
    monkeypatch,
):
    monkeypatch.setattr(
        redactions,
        "get_document_or_404",
        lambda document_id: {"documentId": document_id},
    )

    monkeypatch.setattr(
        redactions,
        "save_redaction_decisions",
        lambda **kwargs: {
            "saved": False,
            "revision": 5,
        },
        raising=False,
    )

    request = SaveRedactionDecisionsRequest(
        documentId="document-123",
        decisions=[],
        expectedRevision=4,
    )

    with pytest.raises(HTTPException) as exc_info:
        await redactions.save_document_redaction_decisions(
            "document-123",
            request,
        )

    assert exc_info.value.status_code == 409


@pytest.mark.anyio
async def test_apply_redactions_queues_redaction_run(
    monkeypatch,
):
    monkeypatch.setattr(
        redactions,
        "get_document_or_404",
        lambda document_id: {
            "documentId": document_id,
        },
    )

    captured = {}

    def fake_create_redaction_run(**kwargs):
        captured.update(kwargs)

        return {
            "created": True,
            "runId": kwargs["run_id"],
            "reviewRevision": kwargs["expected_review_revision"],
        }

    monkeypatch.setattr(
        redactions,
        "create_redaction_run",
        fake_create_redaction_run,
    )

    monkeypatch.setattr(
        redactions,
        "send_redaction_processing_message",
        lambda **kwargs: "message-123",
    )

    monkeypatch.setattr(
        redactions,
        "mark_redaction_run_queued",
        lambda **kwargs: True,
    )

    request = ApplyRedactionsRequest(
        documentId="document-123",
        decisions=[
            {
                "kind": "text",
                "pageNumber": 1,
                "itemId": "item-1",
                "start": 0,
                "end": 5,
                "text": "hello",
                "source": "manual",
                "action": "redact",
            }
        ],
        expectedRevision=4,
    )

    response = await redactions.apply_redactions(
        document_id="document-123",
        request=request,
    )

    assert response["documentId"] == "document-123"
    assert response["status"] == "queued"
    assert response["runId"] == captured["run_id"]

    assert captured["document_id"] == "document-123"
    assert captured["expected_review_revision"] == 4


@pytest.mark.anyio
async def test_apply_redactions_returns_503_when_sqs_enqueue_fails(
    monkeypatch,
):
    monkeypatch.setattr(
        redactions,
        "get_document_or_404",
        lambda document_id: {
            "documentId": document_id,
        },
    )

    monkeypatch.setattr(
        redactions,
        "create_redaction_run",
        lambda **kwargs: {
            "created": True,
            "runId": kwargs["run_id"],
            "reviewRevision": kwargs["expected_review_revision"],
        },
    )

    def fail_send(**kwargs):
        raise RuntimeError("SQS unavailable")

    monkeypatch.setattr(
        redactions,
        "send_redaction_processing_message",
        fail_send,
    )

    failed_runs = []

    monkeypatch.setattr(
        redactions,
        "fail_redaction_run_enqueue",
        lambda **kwargs: failed_runs.append(kwargs) or True,
    )

    request = ApplyRedactionsRequest(
        documentId="document-123",
        decisions=[
            {
                "kind": "text",
                "pageNumber": 1,
                "itemId": "item-1",
                "start": 0,
                "end": 5,
                "text": "hello",
                "source": "manual",
                "action": "redact",
            }
        ],
        expectedRevision=4,
    )

    with pytest.raises(HTTPException) as exc_info:
        await redactions.apply_redactions(
            document_id="document-123",
            request=request,
        )

    assert exc_info.value.status_code == 503
    assert len(failed_runs) == 1
    assert failed_runs[0]["error_message"] == ("The redaction run could not be queued")


@pytest.mark.anyio
async def test_apply_redactions_returns_409_when_run_is_superseded_during_enqueue(
    monkeypatch,
):
    monkeypatch.setattr(
        redactions,
        "get_document_or_404",
        lambda document_id: {
            "documentId": document_id,
        },
    )

    monkeypatch.setattr(
        redactions,
        "create_redaction_run",
        lambda **kwargs: {
            "created": True,
            "runId": kwargs["run_id"],
            "reviewRevision": kwargs["expected_review_revision"],
        },
    )

    monkeypatch.setattr(
        redactions,
        "send_redaction_processing_message",
        lambda **kwargs: "message-123",
    )

    monkeypatch.setattr(
        redactions,
        "mark_redaction_run_queued",
        lambda **kwargs: False,
    )

    request = ApplyRedactionsRequest(
        documentId="document-123",
        decisions=[
            {
                "kind": "text",
                "pageNumber": 1,
                "itemId": "item-1",
                "start": 0,
                "end": 5,
                "text": "hello",
                "source": "manual",
                "action": "redact",
            }
        ],
        expectedRevision=4,
    )

    with pytest.raises(HTTPException) as exc_info:
        await redactions.apply_redactions(
            document_id="document-123",
            request=request,
        )

    assert exc_info.value.status_code == 409
