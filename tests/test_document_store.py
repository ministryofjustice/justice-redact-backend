from types import SimpleNamespace

from app.services import document_store


class FakeSession:
    def __init__(self, document):
        self.document = document

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def get(self, model, document_id):
        return self.document


def test_is_document_processing_owner_returns_true_for_current_owner(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        status="processing",
        processing_job_id="job-123",
        processing_claim_id="claim-123",
    )

    monkeypatch.setattr(
        document_store,
        "SessionLocal",
        lambda: FakeSession(document),
    )

    assert document_store.is_document_processing_owner(
        document_id="document-123",
        job_id="job-123",
        claim_id="claim-123",
    ) is True


def test_is_document_processing_owner_returns_false_after_abandonment(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        status="abandoned",
        processing_job_id="job-123",
        processing_claim_id=None,
    )

    monkeypatch.setattr(
        document_store,
        "SessionLocal",
        lambda: FakeSession(document),
    )

    assert document_store.is_document_processing_owner(
        document_id="document-123",
        job_id="job-123",
        claim_id="claim-123",
    ) is False


def test_is_document_processing_owner_returns_false_for_stale_claim(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        status="processing",
        processing_job_id="job-123",
        processing_claim_id="new-claim",
    )

    monkeypatch.setattr(
        document_store,
        "SessionLocal",
        lambda: FakeSession(document),
    )

    assert document_store.is_document_processing_owner(
        document_id="document-123",
        job_id="job-123",
        claim_id="old-claim",
    ) is False


def test_is_document_processing_owner_returns_false_when_document_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        document_store,
        "SessionLocal",
        lambda: FakeSession(None),
    )

    assert document_store.is_document_processing_owner(
        document_id="document-123",
        job_id="job-123",
        claim_id="claim-123",
    ) is False
