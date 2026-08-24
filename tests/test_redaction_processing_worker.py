import json
import pytest

from app.workers import redaction_processing_worker as worker


class FakeThread:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass

    def join(self, timeout=None):
        pass


def _run_state():
    return {
        "runId": "run-123",
        "documentId": "document-123",
        "reviewRevision": 4,
        "status": "queued",
        "decisionsSnapshot": {
            "documentId": "document-123",
            "decisions": [
                {
                    "kind": "image",
                    "pageNumber": 1,
                    "imageId": "image-123",
                    "action": "redact",
                    "source": "manual",
                }
            ],
        },
        "attemptCount": 0,
        "claimId": None,
        "leaseExpiresAt": None,
        "pageCounts": None,
        "errorMessage": None,
        "createdAt": None,
        "startedAt": None,
        "completedAt": None,
        "cancelledAt": None,
    }


def _message():
    return {
        "ReceiptHandle": "receipt-123",
        "Body": json.dumps(
            {
                "schemaVersion": 1,
                "jobType": "redaction_processing",
                "runId": "run-123",
                "documentId": "document-123",
            }
        ),
        "Attributes": {
            "ApproximateReceiveCount": "2",
        },
    }


def test_redaction_worker_processes_snapshot_and_completes_run(
    monkeypatch,
):
    monkeypatch.setattr(
        worker,
        "get_redaction_run",
        lambda run_id: _run_state(),
    )

    claim_calls = []

    def claim_run(**kwargs):
        claim_calls.append(kwargs)
        return True

    monkeypatch.setattr(
        worker,
        "claim_redaction_run",
        claim_run,
    )

    monkeypatch.setattr(
        worker,
        "is_redaction_run_owner",
        lambda **kwargs: True,
    )

    monkeypatch.setattr(
        worker.threading,
        "Thread",
        FakeThread,
    )

    def apply_redactions(**kwargs):
        assert kwargs["document_id"] == "document-123"
        assert kwargs["run_id"] == "run-123"

        request = kwargs["request"]

        assert request.documentId == "document-123"
        assert request.expectedRevision == 4
        assert len(request.decisions) == 1
        assert request.decisions[0].kind == "image"

        assert kwargs["is_redaction_active"]() is True

        return {
            "pageCounts": {
                "original": 10,
                "redacted": 8,
                "exempt": 1,
                "deleted": 1,
            }
        }

    monkeypatch.setattr(
        worker,
        "apply_redactions_for_document",
        apply_redactions,
    )

    completion_calls = []

    def complete_run(**kwargs):
        completion_calls.append(kwargs)
        return True

    monkeypatch.setattr(
        worker,
        "complete_redaction_run",
        complete_run,
    )

    deleted_messages = []

    monkeypatch.setattr(
        worker,
        "delete_redaction_processing_message",
        lambda *, receipt_handle: deleted_messages.append(receipt_handle),
    )

    failed_runs = []

    monkeypatch.setattr(
        worker,
        "fail_redaction_run",
        lambda **kwargs: failed_runs.append(kwargs),
    )

    worker.process_sqs_message(_message())

    assert len(claim_calls) == 1
    assert claim_calls[0]["run_id"] == "run-123"
    assert claim_calls[0]["attempt_count"] == 2

    assert len(completion_calls) == 1
    assert completion_calls[0]["run_id"] == "run-123"
    assert completion_calls[0]["claim_id"] == claim_calls[0]["claim_id"]
    assert completion_calls[0]["page_counts"] == {
        "original": 10,
        "redacted": 8,
        "exempt": 1,
        "deleted": 1,
    }

    assert deleted_messages == ["receipt-123"]
    assert failed_runs == []


def test_cancelled_redaction_processing_cleans_only_run_prefix(
    monkeypatch,
):
    monkeypatch.setattr(
        worker,
        "get_redaction_run",
        lambda run_id: _run_state(),
    )

    monkeypatch.setattr(
        worker,
        "claim_redaction_run",
        lambda **kwargs: True,
    )

    monkeypatch.setattr(
        worker.threading,
        "Thread",
        FakeThread,
    )

    def cancel_processing(**kwargs):
        raise worker.RedactionProcessingCancelled()

    monkeypatch.setattr(
        worker,
        "apply_redactions_for_document",
        cancel_processing,
    )

    deleted_prefixes = []

    monkeypatch.setattr(
        worker,
        "delete_s3_prefix",
        lambda prefix: deleted_prefixes.append(prefix),
    )

    deleted_messages = []

    monkeypatch.setattr(
        worker,
        "delete_redaction_processing_message",
        lambda *, receipt_handle: deleted_messages.append(receipt_handle),
    )

    failed_runs = []

    monkeypatch.setattr(
        worker,
        "fail_redaction_run",
        lambda **kwargs: failed_runs.append(kwargs),
    )

    worker.process_sqs_message(_message())

    assert deleted_prefixes == ["documents/document-123/redaction-runs/run-123/"]
    assert deleted_messages == ["receipt-123"]
    assert failed_runs == []


@pytest.mark.parametrize(
    ("receive_count", "expected_terminal"),
    [
        ("1", False),
        ("3", True),
    ],
)
def test_redaction_worker_failure_uses_sqs_receive_count_for_retry(
    monkeypatch,
    receive_count,
    expected_terminal,
):
    monkeypatch.setattr(
        worker,
        "get_redaction_run",
        lambda run_id: _run_state(),
    )

    monkeypatch.setattr(
        worker,
        "claim_redaction_run",
        lambda **kwargs: True,
    )

    monkeypatch.setattr(
        worker.threading,
        "Thread",
        FakeThread,
    )

    def fail_processing(**kwargs):
        raise RuntimeError("PDF generation failed")

    monkeypatch.setattr(
        worker,
        "apply_redactions_for_document",
        fail_processing,
    )

    failure_calls = []

    def fail_run(**kwargs):
        failure_calls.append(kwargs)
        return True

    monkeypatch.setattr(
        worker,
        "fail_redaction_run",
        fail_run,
    )

    deleted_messages = []

    monkeypatch.setattr(
        worker,
        "delete_redaction_processing_message",
        lambda *, receipt_handle: deleted_messages.append(receipt_handle),
    )

    message = _message()
    message["Attributes"]["ApproximateReceiveCount"] = receive_count

    with pytest.raises(
        RuntimeError,
        match="PDF generation failed",
    ):
        worker.process_sqs_message(message)

    assert len(failure_calls) == 1
    assert failure_calls[0]["run_id"] == "run-123"
    assert failure_calls[0]["terminal"] is expected_terminal
    assert failure_calls[0]["error_message"] == "Redaction processing failed"

    # Do not acknowledge a genuine processing failure.
    # SQS must redeliver it or eventually move it to the DLQ.
    assert deleted_messages == []
