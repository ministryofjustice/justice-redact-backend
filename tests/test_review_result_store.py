from types import SimpleNamespace
from datetime import datetime, timezone

from app.services import review_result_store


class FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, document, review_result=None):
        self.document = document
        self.review_result = review_result
        self.added = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def execute(self, statement):
        return FakeScalarResult(self.document)

    def get(self, model, document_id):
        return self.review_result

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.committed = True


def test_publish_review_result_if_processing_owner_publishes_for_current_owner(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        status="processing",
        processing_job_id="job-123",
        processing_claim_id="claim-123",
        processing_completed_at=None,
        processing_lease_expires_at=None,
        error_message=None,
    )

    session = FakeSession(document)

    monkeypatch.setattr(
        review_result_store,
        "SessionLocal",
        lambda: session,
    )

    completed_at = datetime.now(timezone.utc)

    published = review_result_store.publish_review_result_if_processing_owner(
        document_id="document-123",
        job_id="job-123",
        claim_id="claim-123",
        review_json={"documentId": "document-123"},
        completed_at=completed_at,
    )

    assert published is True
    assert len(session.added) == 1
    assert session.added[0].document_id == "document-123"
    assert session.added[0].review_json == {"documentId": "document-123"}
    assert session.committed is True
    assert document.status == "ready_for_review"

    assert document.processing_completed_at == completed_at
    assert document.processing_claim_id is None
    assert document.processing_lease_expires_at is None
    assert document.error_message is None


def test_publish_review_result_if_processing_owner_rejects_abandoned_document(
    monkeypatch,
):
    session = FakeSession(document=None)

    monkeypatch.setattr(
        review_result_store,
        "SessionLocal",
        lambda: session,
    )

    published = review_result_store.publish_review_result_if_processing_owner(
        document_id="document-123",
        job_id="job-123",
        claim_id="claim-123",
        review_json={"documentId": "document-123"},
        completed_at=datetime.now(timezone.utc),
    )

    assert published is False
    assert session.added == []
    assert session.committed is False
