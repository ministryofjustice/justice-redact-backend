import pytest
from fastapi import HTTPException

from app.api.routers import exports


def _document(
    *,
    current_run_id: str = "run-123",
    status: str = "redaction_complete",
):
    return {
        "documentId": "document-123",
        "filename": "example.pdf",
        "status": status,
        "currentRedactionRunId": current_run_id,
    }


def _completed_run(
    *,
    run_id: str = "run-123",
    document_id: str = "document-123",
):
    return {
        "runId": run_id,
        "documentId": document_id,
        "reviewRevision": 4,
        "status": "completed",
        "pageCounts": {
            "original": 10,
            "exempt": 1,
            "deleted": 2,
            "redacted": 7,
        },
    }


@pytest.mark.anyio
async def test_get_document_export_returns_requested_current_completed_run(
    monkeypatch,
):
    monkeypatch.setattr(
        exports,
        "get_document_or_404",
        lambda document_id: _document(),
    )

    monkeypatch.setattr(
        exports,
        "get_redaction_run",
        lambda run_id: _completed_run(run_id=run_id),
        raising=False,
    )

    monkeypatch.setattr(
        exports,
        "object_exists_in_s3",
        lambda key: True,
    )

    response = await exports.get_document_export(
        "document-123",
        "run-123",
    )

    assert response == {
        "documentId": "document-123",
        "runId": "run-123",
        "filename": "example.pdf",
        "status": "redaction_complete",
        "redactedExportUrl": (
            "/documents/document-123/redaction-runs/run-123/redacted-file"
        ),
        "vettedExportUrl": (
            "/documents/document-123/redaction-runs/run-123/vetted-file"
        ),
        "exemptExportUrl": (
            "/documents/document-123/redaction-runs/run-123/exempt-file"
        ),
        "pageCount": 10,
        "pageCounts": {
            "original": 10,
            "exempt": 1,
            "deleted": 2,
            "redacted": 7,
        },
    }


@pytest.mark.anyio
async def test_get_document_export_returns_superseded_completed_run_metadata(
    monkeypatch,
):
    monkeypatch.setattr(
        exports,
        "get_document_or_404",
        lambda document_id: _document(
            current_run_id="run-new",
            status="applying_redactions",
        ),
    )

    monkeypatch.setattr(
        exports,
        "get_redaction_run",
        lambda run_id: _completed_run(run_id=run_id),
        raising=False,
    )

    monkeypatch.setattr(
        exports,
        "object_exists_in_s3",
        lambda key: True,
    )

    response = await exports.get_document_export(
        "document-123",
        "run-old",
    )

    assert response == {
        "documentId": "document-123",
        "runId": "run-old",
        "filename": "example.pdf",
        "status": "redaction_complete",
        "redactedExportUrl": (
            "/documents/document-123/redaction-runs/run-old/redacted-file"
        ),
        "vettedExportUrl": (
            "/documents/document-123/redaction-runs/run-old/vetted-file"
        ),
        "exemptExportUrl": (
            "/documents/document-123/redaction-runs/run-old/exempt-file"
        ),
        "pageCount": 10,
        "pageCounts": {
            "original": 10,
            "exempt": 1,
            "deleted": 2,
            "redacted": 7,
        },
    }


@pytest.mark.anyio
async def test_download_redacted_file_rejects_superseded_run(
    monkeypatch,
):
    monkeypatch.setattr(
        exports,
        "get_document_or_404",
        lambda document_id: _document(
            current_run_id="run-new",
        ),
    )

    monkeypatch.setattr(
        exports,
        "get_redaction_run",
        lambda run_id: _completed_run(run_id=run_id),
        raising=False,
    )

    object_reads = []

    monkeypatch.setattr(
        exports,
        "get_object_from_s3",
        lambda key: object_reads.append(key),
    )

    with pytest.raises(HTTPException) as exc_info:
        await exports.download_redacted_file(
            "document-123",
            "run-old",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Redaction run has been superseded"

    assert object_reads == []


@pytest.mark.anyio
async def test_download_vetted_file_rejects_superseded_run(
    monkeypatch,
):
    monkeypatch.setattr(
        exports,
        "get_document_or_404",
        lambda document_id: _document(
            current_run_id="run-new",
        ),
    )

    monkeypatch.setattr(
        exports,
        "get_redaction_run",
        lambda run_id: _completed_run(run_id=run_id),
    )

    object_reads = []

    monkeypatch.setattr(
        exports,
        "get_object_from_s3",
        lambda key: object_reads.append(key),
    )

    with pytest.raises(HTTPException) as exc_info:
        await exports.download_vetted_file(
            "document-123",
            "run-old",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Redaction run has been superseded"

    assert object_reads == []


@pytest.mark.anyio
async def test_download_exempt_file_rejects_superseded_run(
    monkeypatch,
):
    monkeypatch.setattr(
        exports,
        "get_document_or_404",
        lambda document_id: _document(
            current_run_id="run-new",
        ),
    )

    monkeypatch.setattr(
        exports,
        "get_redaction_run",
        lambda run_id: _completed_run(run_id=run_id),
    )

    object_reads = []

    monkeypatch.setattr(
        exports,
        "get_object_from_s3",
        lambda key: object_reads.append(key),
    )

    with pytest.raises(HTTPException) as exc_info:
        await exports.download_exempt_file(
            "document-123",
            "run-old",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Redaction run has been superseded"

    assert object_reads == []
