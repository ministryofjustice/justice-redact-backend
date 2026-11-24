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
        lambda *, receipt_handle: deleted_messages.append(receipt_handle),
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


def test_completed_processing_sends_notification_and_deletes_message(
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

    monkeypatch.setattr(
        worker,
        "process_document_pipeline",
        lambda *args, **kwargs: None,
    )

    notification_attempts = []

    monkeypatch.setattr(
        worker,
        "send_ready_notification_if_pending",
        lambda document_id: (notification_attempts.append(document_id) or True),
    )

    deleted_messages = []
    failed_attempts = []

    monkeypatch.setattr(
        worker,
        "delete_document_processing_message",
        lambda *, receipt_handle: deleted_messages.append(receipt_handle),
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

    assert notification_attempts == [
        "document-123",
    ]

    assert deleted_messages == [
        "receipt-123",
    ]

    assert failed_attempts == []


def test_notification_failure_after_processing_leaves_message_for_retry(
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

    monkeypatch.setattr(
        worker,
        "process_document_pipeline",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        worker,
        "send_ready_notification_if_pending",
        lambda document_id: False,
    )

    deleted_messages = []
    failed_attempts = []

    monkeypatch.setattr(
        worker,
        "delete_document_processing_message",
        lambda *, receipt_handle: deleted_messages.append(receipt_handle),
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

    assert deleted_messages == []

    # Notify failure must never turn successfully
    # processed work into a processing failure.
    assert failed_attempts == []


def test_ready_document_retries_pending_notification_only(
    monkeypatch,
):
    monkeypatch.setattr(
        worker,
        "get_document",
        lambda document_id: {
            "documentId": document_id,
            "status": "ready_for_review",
            "documentType": "nomis",
            "processingJobId": "job-123",
        },
    )

    notification_attempts = []

    monkeypatch.setattr(
        worker,
        "send_ready_notification_if_pending",
        lambda document_id: (notification_attempts.append(document_id) or True),
    )

    deleted_messages = []

    monkeypatch.setattr(
        worker,
        "delete_document_processing_message",
        lambda *, receipt_handle: deleted_messages.append(receipt_handle),
    )

    # Processing must not run again.
    monkeypatch.setattr(
        worker,
        "process_document_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("processing pipeline should not run")
        ),
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
                "ApproximateReceiveCount": "2",
            },
        }
    )

    assert notification_attempts == [
        "document-123",
    ]

    assert deleted_messages == [
        "receipt-123",
    ]


def test_ready_document_keeps_message_when_notification_retry_fails(
    monkeypatch,
):
    monkeypatch.setattr(
        worker,
        "get_document",
        lambda document_id: {
            "documentId": document_id,
            "status": "ready_for_review",
            "documentType": "nomis",
            "processingJobId": "job-123",
        },
    )

    monkeypatch.setattr(
        worker,
        "send_ready_notification_if_pending",
        lambda document_id: False,
    )

    deleted_messages = []

    monkeypatch.setattr(
        worker,
        "delete_document_processing_message",
        lambda *, receipt_handle: deleted_messages.append(receipt_handle),
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
                "ApproximateReceiveCount": "2",
            },
        }
    )

    assert deleted_messages == []


def test_send_ready_notification_builds_review_link_and_marks_sent(
    monkeypatch,
):
    monkeypatch.setattr(
        worker.settings,
        "auth_frontend_base_url",
        "https://justice-redact.example.test/",
    )

    monkeypatch.setattr(
        worker,
        "get_pending_ready_notification",
        lambda document_id: {
            "email": "user@justice.gov.uk",
            "filename": "example.pdf",
        },
    )

    sent_emails = []

    monkeypatch.setattr(
        worker,
        "send_document_ready_email",
        lambda **kwargs: (sent_emails.append(kwargs) or "notification-123"),
    )

    marked = []

    monkeypatch.setattr(
        worker,
        "mark_ready_notification_sent",
        lambda **kwargs: (marked.append(kwargs) or True),
    )

    result = worker.send_ready_notification_if_pending(
        "document/123",
    )

    assert result is True

    assert sent_emails == [
        {
            "email": "user@justice.gov.uk",
            "filename": "example.pdf",
            "document_link": (
                "https://justice-redact.example.test/"
                "review?documentId=document%2F123"
            ),
        }
    ]

    assert len(marked) == 1
    assert marked[0]["document_id"] == "document/123"
    assert isinstance(
        marked[0]["sent_at"],
        worker.datetime,
    )


def test_send_ready_notification_does_nothing_when_not_pending(
    monkeypatch,
):
    monkeypatch.setattr(
        worker,
        "get_pending_ready_notification",
        lambda document_id: None,
    )

    monkeypatch.setattr(
        worker,
        "send_document_ready_email",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("email should not be sent")
        ),
    )

    result = worker.send_ready_notification_if_pending(
        "document-123",
    )

    assert result is True


def test_send_ready_notification_returns_false_when_notify_fails(
    monkeypatch,
):
    monkeypatch.setattr(
        worker.settings,
        "auth_frontend_base_url",
        "https://justice-redact.example.test",
    )

    monkeypatch.setattr(
        worker,
        "get_pending_ready_notification",
        lambda document_id: {
            "email": "user@justice.gov.uk",
            "filename": "example.pdf",
        },
    )

    def fail_notification(**kwargs):
        raise RuntimeError("Notify unavailable")

    monkeypatch.setattr(
        worker,
        "send_document_ready_email",
        fail_notification,
    )

    marked = []

    monkeypatch.setattr(
        worker,
        "mark_ready_notification_sent",
        lambda **kwargs: marked.append(kwargs),
    )

    result = worker.send_ready_notification_if_pending(
        "document-123",
    )

    assert result is False
    assert marked == []
