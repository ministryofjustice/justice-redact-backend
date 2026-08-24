import json

from app.services.document_processing_service import (
    DocumentProcessingCancelled,
)
from app.workers import document_processing_worker as worker


class FakeThread:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass

    def join(self, timeout=None):
        pass


def test_cancelled_processing_is_cleaned_up_and_not_marked_failed(
    monkeypatch,
):
    monkeypatch.setattr(
        worker,
        "get_document",
        lambda document_id: {
            "documentId": document_id,
            "status": "queued",
            "documentType": "nomis",
            "processingJobId": "job-123",
        },
    )

    monkeypatch.setattr(
        worker,
        "try_claim_document_processing",
        lambda **kwargs: True,
    )

    monkeypatch.setattr(
        worker.threading,
        "Thread",
        FakeThread,
    )

    def cancel_pipeline(*args, **kwargs):
        raise DocumentProcessingCancelled()

    monkeypatch.setattr(
        worker,
        "process_document_pipeline",
        cancel_pipeline,
    )

    deleted_prefixes = []
    deleted_messages = []
    failed_attempts = []

    monkeypatch.setattr(
        worker,
        "delete_s3_prefix",
        lambda prefix: deleted_prefixes.append(prefix),
    )

    monkeypatch.setattr(
        worker,
        "delete_document_processing_message",
        lambda *, receipt_handle: deleted_messages.append(
            receipt_handle
        ),
    )

    monkeypatch.setattr(
        worker,
        "fail_document_processing_attempt",
        lambda **kwargs: failed_attempts.append(kwargs),
    )

    worker.process_sqs_message(
        {
            "ReceiptHandle": "receipt-123",
            "Body": json.dumps(
                {
                    "schemaVersion": 1,
                    "jobType": "document_processing",
                    "jobId": "job-123",
                    "documentId": "document-123",
                }
            ),
            "Attributes": {
                "ApproximateReceiveCount": "1",
            },
        }
    )

    assert deleted_prefixes == [
        "documents/document-123/",
    ]
    assert deleted_messages == ["receipt-123"]
    assert failed_attempts == []
