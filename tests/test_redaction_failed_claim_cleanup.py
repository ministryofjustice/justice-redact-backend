
import json

import pytest

from app.services import s3_service
from app.services.s3_keys import redaction_run_export_prefix
from app.workers import redaction_processing_worker as worker
from justice_redact.pdf_handler.apply.export_security_audit import (
    PDFExportSecurityError,
)


DOCUMENT_ID = "document-123"
RUN_ID = "run-123"
CLAIM_ID = "claim-attempt"
PUBLISHED_CLAIM_ID = "claim-published"


class FakeThread:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass

    def join(self, timeout=None):
        pass


def _message(receive_count=2):
    return {
        "ReceiptHandle": "receipt-123",
        "Body": json.dumps({
            "schemaVersion": 1,
            "jobType": "redaction_processing",
            "runId": RUN_ID,
            "documentId": DOCUMENT_ID,
        }),
        "Attributes": {
            "ApproximateReceiveCount": str(receive_count),
        },
    }


def _run_state():
    return {
        "runId": RUN_ID,
        "documentId": DOCUMENT_ID,
        "reviewRevision": 4,
        "status": "queued",
        "processingProgress": 0,
        "decisionsSnapshot": {
            "documentId": DOCUMENT_ID,
            "decisions": [{
                "kind": "image",
                "pageNumber": 1,
                "imageId": "image-123",
                "action": "redact",
                "source": "manual",
            }],
        },
        "attemptCount": 0,
        "claimId": None,
        "pageCounts": None,
    }


def _configure_worker(
    monkeypatch,
    *,
    failure_accepted=True,
    processing_error=None,
    cleanup_error=None,
):
    calls = {
        "claims": [],
        "failures": [],
        "completions": [],
        "cleanup": [],
        "acknowledgements": [],
    }

    prefix = redaction_run_export_prefix(
        DOCUMENT_ID,
        RUN_ID,
        CLAIM_ID,
    )

    published_prefix = redaction_run_export_prefix(
        DOCUMENT_ID,
        RUN_ID,
        PUBLISHED_CLAIM_ID,
    )

    objects = {
        prefix + "exports/redacted.pdf": b"PARTIAL",
        published_prefix + "exports/redacted.pdf": b"PUBLISHED",
    }

    monkeypatch.setattr(
        worker.threading,
        "Thread",
        FakeThread,
    )

    monkeypatch.setattr(
        worker,
        "uuid4",
        lambda: CLAIM_ID,
    )

    monkeypatch.setattr(
        worker,
        "get_redaction_run",
        lambda run_id: _run_state(),
    )

    def claim(**kwargs):
        calls["claims"].append(kwargs)
        return True

    monkeypatch.setattr(
        worker,
        "claim_redaction_run",
        claim,
    )

    monkeypatch.setattr(
        worker,
        "is_redaction_run_owner",
        lambda **kwargs: True,
    )

    monkeypatch.setattr(
        worker,
        "update_redaction_run_processing_progress",
        lambda **kwargs: True,
    )

    def process(**kwargs):
        assert kwargs["claim_id"] == CLAIM_ID

        if processing_error is not None:
            raise processing_error

        return {
            "pageCounts": {
                "original": 1,
                "redacted": 1,
                "exempt": 0,
                "deleted": 0,
            }
        }

    monkeypatch.setattr(
        worker,
        "apply_redactions_for_document",
        process,
    )

    def complete(**kwargs):
        calls["completions"].append(kwargs)
        return True

    monkeypatch.setattr(
        worker,
        "complete_redaction_run",
        complete,
    )

    def fail(**kwargs):
        calls["failures"].append(kwargs)
        return failure_accepted

    monkeypatch.setattr(
        worker,
        "fail_redaction_run",
        fail,
    )

    def cleanup(cleanup_prefix):
        calls["cleanup"].append(cleanup_prefix)

        if cleanup_error is not None:
            raise cleanup_error

        for key in list(objects):
            if key.startswith(cleanup_prefix):
                del objects[key]

    monkeypatch.setattr(
        worker,
        "delete_s3_prefix",
        cleanup,
    )

    monkeypatch.setattr(
        worker,
        "delete_redaction_processing_message",
        lambda **kwargs: calls[
            "acknowledgements"
        ].append(kwargs),
    )

    return calls, objects, prefix, published_prefix


@pytest.mark.parametrize("receive_count", [2, 3])
@pytest.mark.parametrize(
    "error_kind",
    ["audit", "partial_upload"],
)
def test_failed_claim_cleans_only_its_own_s3_prefix(
    monkeypatch,
    receive_count,
    error_kind,
):
    error = (
        PDFExportSecurityError("Synthetic audit rejection")
        if error_kind == "audit"
        else OSError("Synthetic upload failure")
    )

    calls, objects, prefix, published_prefix = (
        _configure_worker(
            monkeypatch,
            processing_error=error,
        )
    )

    with pytest.raises(type(error)):
        worker.process_sqs_message(
            _message(receive_count)
        )

    assert calls["cleanup"] == [prefix]
    assert calls["completions"] == []
    assert len(calls["failures"]) == 1

    assert calls["failures"][0]["terminal"] is (
        receive_count >= worker.MAX_RECEIVE_COUNT
    )

    assert calls["acknowledgements"] == []

    assert not any(
        key.startswith(prefix)
        for key in objects
    )

    assert (
        objects[published_prefix + "exports/redacted.pdf"]
        == b"PUBLISHED"
    )


def test_rejected_failure_transition_never_deletes_s3(
    monkeypatch,
):
    calls, objects, prefix, published_prefix = (
        _configure_worker(
            monkeypatch,
            failure_accepted=False,
            processing_error=OSError("Stale failure"),
        )
    )

    worker.process_sqs_message(_message())

    assert calls["cleanup"] == []
    assert calls["completions"] == []
    assert len(calls["failures"]) == 1
    assert len(calls["acknowledgements"]) == 1

    assert prefix + "exports/redacted.pdf" in objects
    assert published_prefix + "exports/redacted.pdf" in objects


def test_cleanup_failure_preserves_original_exception(
    monkeypatch,
):
    calls, objects, prefix, published_prefix = (
        _configure_worker(
            monkeypatch,
            processing_error=OSError(
                "Original export failure"
            ),
            cleanup_error=RuntimeError(
                "Synthetic S3 cleanup failure"
            ),
        )
    )

    with pytest.raises(
        OSError,
        match="Original export failure",
    ):
        worker.process_sqs_message(_message())

    assert calls["cleanup"] == [prefix]
    assert len(calls["failures"]) == 1
    assert calls["completions"] == []

    assert published_prefix + "exports/redacted.pdf" in objects


def test_cancellation_does_not_delete_without_failure_transition(
    monkeypatch,
):
    calls, objects, prefix, published_prefix = (
        _configure_worker(
            monkeypatch,
            processing_error=worker.RedactionProcessingCancelled(
                "Synthetic cancellation"
            ),
        )
    )

    worker.process_sqs_message(_message())

    assert calls["cleanup"] == []
    assert calls["failures"] == []
    assert calls["completions"] == []
    assert len(calls["acknowledgements"]) == 1

    assert published_prefix + "exports/redacted.pdf" in objects


def test_successful_completion_does_not_delete_exports(
    monkeypatch,
):
    calls, objects, prefix, published_prefix = (
        _configure_worker(monkeypatch)
    )

    worker.process_sqs_message(_message())

    assert calls["cleanup"] == []
    assert calls["failures"] == []
    assert len(calls["completions"]) == 1
    assert len(calls["acknowledgements"]) == 1

    assert prefix + "exports/redacted.pdf" in objects
    assert published_prefix + "exports/redacted.pdf" in objects


def test_s3_reports_individual_object_deletion_failures(
    monkeypatch,
):
    prefix = redaction_run_export_prefix(
        DOCUMENT_ID,
        RUN_ID,
        CLAIM_ID,
    )

    class FakePaginator:
        def paginate(self, **kwargs):
            assert kwargs["Prefix"] == prefix

            return [{
                "Contents": [{
                    "Key": prefix + "exports/redacted.pdf",
                }],
            }]

    monkeypatch.setattr(
        s3_service.s3_client,
        "get_paginator",
        lambda operation: FakePaginator(),
    )

    monkeypatch.setattr(
        s3_service.s3_client,
        "delete_objects",
        lambda **kwargs: {
            "Errors": [{
                "Key": prefix + "exports/redacted.pdf",
                "Code": "AccessDenied",
            }],
        },
    )

    with pytest.raises(
        RuntimeError,
        match="could not delete all listed objects",
    ):
        s3_service.delete_s3_prefix(prefix)
