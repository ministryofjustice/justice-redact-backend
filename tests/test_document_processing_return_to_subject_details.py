from types import SimpleNamespace

import pytest

from app.services import document_store


class FakeSession:
    def __init__(self, document):
        self.document = document
        self.commits = 0
        self.lock_requested = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def get(self, model, document_id, *, with_for_update=False):
        assert model is document_store.Document
        assert document_id == "document-123"
        self.lock_requested = with_for_update
        return self.document

    def commit(self):
        self.commits += 1


def make_document(status):
    return SimpleNamespace(
        status=status,
        owner_user_id="user-123",
        filename="original.pdf",
        subject_name="Test Subject",
        subject_prison_number="A1234BC",
        other_phrases="",
        processing_job_id="job-old",
        processing_claim_id="claim-old",
        processing_lease_expires_at="old-lease",
        processing_progress=75,
        processing_attempt_count=2,
        processing_started_at="started",
        processing_completed_at=None,
        error_message="previous error",
    )


@pytest.mark.parametrize(
    "status",
    [
        "uploaded",
        "enqueue_failed",
        "enqueueing",
        "queued",
        "processing",
        "retrying",
        "failed",
    ],
)
def test_return_to_subject_details_invalidates_processing(
    monkeypatch,
    status,
):
    document = make_document(status)
    session = FakeSession(document)

    monkeypatch.setattr(
        document_store,
        "SessionLocal",
        lambda: session,
    )

    result = (
        document_store.request_processing_return_to_subject_details(
            document_id="document-123",
        )
    )

    assert result == "subject-details"
    assert document.status == "uploaded"

    assert document.processing_job_id is None
    assert document.processing_claim_id is None
    assert document.processing_lease_expires_at is None
    assert document.processing_progress == 0
    assert document.processing_attempt_count == 0
    assert document.processing_started_at is None
    assert document.processing_completed_at is None
    assert document.error_message is None

    # Preserve original upload and subject details.
    assert document.filename == "original.pdf"
    assert document.owner_user_id == "user-123"
    assert document.subject_name == "Test Subject"
    assert document.subject_prison_number == "A1234BC"

    assert session.lock_requested is True
    assert session.commits == 1


def test_return_preserves_completed_review(monkeypatch):
    document = make_document("ready_for_review")
    session = FakeSession(document)

    monkeypatch.setattr(
        document_store,
        "SessionLocal",
        lambda: session,
    )

    result = (
        document_store.request_processing_return_to_subject_details(
            document_id="document-123",
        )
    )

    assert result == "review"
    assert document.status == "ready_for_review"
    assert document.processing_job_id == "job-old"
    assert session.lock_requested is True
    assert session.commits == 0


def test_return_rejects_incompatible_workflow_state(monkeypatch):
    document = make_document("applying_redactions")
    session = FakeSession(document)

    monkeypatch.setattr(
        document_store,
        "SessionLocal",
        lambda: session,
    )

    result = (
        document_store.request_processing_return_to_subject_details(
            document_id="document-123",
        )
    )

    assert result == "conflict"
    assert document.status == "applying_redactions"
    assert session.commits == 0


def test_return_handles_missing_document(monkeypatch):
    session = FakeSession(None)

    monkeypatch.setattr(
        document_store,
        "SessionLocal",
        lambda: session,
    )

    result = (
        document_store.request_processing_return_to_subject_details(
            document_id="document-123",
        )
    )

    assert result == "not_found"
    assert session.commits == 0
