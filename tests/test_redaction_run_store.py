from datetime import datetime, timezone
from types import SimpleNamespace

from app.services import redaction_run_store


class FakeSession:
    def __init__(self, redaction_run=None):
        self.redaction_run = redaction_run
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def get(self, model, run_id):
        return self.redaction_run

    def commit(self):
        self.committed = True


class FakeCreateSession:
    def __init__(self, document, decision):
        self.document = document
        self.decision = decision
        self.added = []
        self.committed = False
        self.execute_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def execute(self, statement):
        self.execute_count += 1

        if self.execute_count == 1:
            return FakeScalarResult(self.document)

        return FakeScalarResult(self.decision)

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.committed = True


class FakeRunTransitionSession:
    def __init__(self, document, redaction_run):
        self.document = document
        self.redaction_run = redaction_run
        self.committed = False
        self.execute_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def get(self, model, run_id):
        return self.redaction_run

    def execute(self, statement):
        self.execute_count += 1

        if self.execute_count == 1:
            return FakeScalarResult(self.document)

        return FakeScalarResult(self.redaction_run)

    def commit(self):
        self.committed = True


class FakeCreateWithPreviousRunSession:
    def __init__(self, document, decision, previous_run):
        self.document = document
        self.decision = decision
        self.previous_run = previous_run
        self.added = []
        self.committed = False
        self.execute_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def execute(self, statement):
        self.execute_count += 1

        if self.execute_count == 1:
            return FakeScalarResult(self.document)

        if self.execute_count == 2:
            return FakeScalarResult(self.decision)

        return FakeScalarResult(self.previous_run)

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.committed = True


class FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


def test_get_redaction_run_returns_run_state(
    monkeypatch,
):
    now = datetime.now(timezone.utc)

    redaction_run = SimpleNamespace(
        run_id="run-123",
        document_id="document-123",
        review_revision=4,
        status="queued",
        decisions_snapshot={
            "documentId": "document-123",
            "decisions": [{"id": "decision-1"}],
        },
        attempt_count=0,
        claim_id=None,
        lease_expires_at=None,
        page_counts=None,
        error_message=None,
        created_at=now,
        started_at=None,
        completed_at=None,
        cancelled_at=None,
    )

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: FakeSession(redaction_run),
    )

    result = redaction_run_store.get_redaction_run("run-123")

    assert result == {
        "runId": "run-123",
        "documentId": "document-123",
        "reviewRevision": 4,
        "status": "queued",
        "decisionsSnapshot": {
            "documentId": "document-123",
            "decisions": [{"id": "decision-1"}],
        },
        "attemptCount": 0,
        "claimId": None,
        "leaseExpiresAt": None,
        "pageCounts": None,
        "errorMessage": None,
        "createdAt": now.isoformat(),
        "startedAt": None,
        "completedAt": None,
        "cancelledAt": None,
    }


def test_get_redaction_run_returns_none_when_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: FakeSession(),
    )

    result = redaction_run_store.get_redaction_run("missing-run")

    assert result is None


def test_create_redaction_run_uses_persisted_revision_and_snapshot(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        current_redaction_run_id=None,
        status="ready_for_review",
        redaction_started_at=None,
        redaction_completed_at=None,
        error_message=None,
    )

    decision = SimpleNamespace(
        document_id="document-123",
        revision=4,
        decisions_json={
            "documentId": "document-123",
            "decisions": [{"id": "decision-1"}],
        },
    )

    session = FakeCreateSession(
        document=document,
        decision=decision,
    )

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_run_store.create_redaction_run(
        run_id="run-123",
        document_id="document-123",
        expected_review_revision=4,
    )

    assert result == {
        "created": True,
        "runId": "run-123",
        "reviewRevision": 4,
    }

    assert len(session.added) == 1

    created_run = session.added[0]

    assert created_run.run_id == "run-123"
    assert created_run.document_id == "document-123"
    assert created_run.review_revision == 4
    assert created_run.status == "enqueueing"
    assert created_run.decisions_snapshot == {
        "documentId": "document-123",
        "decisions": [{"id": "decision-1"}],
    }

    assert document.current_redaction_run_id == "run-123"
    assert document.status == "applying_redactions"
    assert document.redaction_started_at is not None
    assert document.redaction_completed_at is None
    assert document.error_message is None

    assert session.committed is True


def test_create_redaction_run_rejects_stale_review_revision(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        current_redaction_run_id=None,
        status="ready_for_review",
        redaction_started_at=None,
        redaction_completed_at=None,
        error_message=None,
    )

    decision = SimpleNamespace(
        document_id="document-123",
        revision=5,
        decisions_json={
            "documentId": "document-123",
            "decisions": [{"id": "latest-decision"}],
        },
    )

    session = FakeCreateSession(
        document=document,
        decision=decision,
    )

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_run_store.create_redaction_run(
        run_id="run-123",
        document_id="document-123",
        expected_review_revision=4,
    )

    assert result == {
        "created": False,
        "reason": "revision_conflict",
        "currentRevision": 5,
    }

    assert session.added == []
    assert session.committed is False

    assert document.current_redaction_run_id is None
    assert document.status == "ready_for_review"


def test_claim_redaction_run_moves_current_run_to_processing(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        current_redaction_run_id="run-123",
        status="applying_redactions",
    )

    redaction_run = SimpleNamespace(
        run_id="run-123",
        document_id="document-123",
        status="queued",
        attempt_count=0,
        claim_id=None,
        lease_expires_at=None,
        started_at=None,
        completed_at=None,
        error_message=None,
    )

    session = FakeRunTransitionSession(
        document=document,
        redaction_run=redaction_run,
    )

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_run_store.claim_redaction_run(
        run_id="run-123",
        claim_id="claim-123",
        attempt_count=2,
        lease_expires_at=datetime.now(timezone.utc),
    )

    assert result is True

    assert redaction_run.status == "processing"
    assert redaction_run.claim_id == "claim-123"
    assert redaction_run.attempt_count == 2
    assert redaction_run.started_at is not None
    assert redaction_run.completed_at is None
    assert redaction_run.error_message is None
    assert session.committed is True


def test_complete_redaction_run_marks_run_and_document_completed(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        current_redaction_run_id="run-123",
        status="applying_redactions",
        redaction_completed_at=None,
        error_message=None,
    )

    redaction_run = SimpleNamespace(
        run_id="run-123",
        document_id="document-123",
        status="processing",
        claim_id="claim-123",
        lease_expires_at=datetime.now(timezone.utc),
        page_counts=None,
        completed_at=None,
        error_message=None,
    )

    session = FakeRunTransitionSession(
        document=document,
        redaction_run=redaction_run,
    )

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_run_store.complete_redaction_run(
        run_id="run-123",
        claim_id="claim-123",
        page_counts={
            "original": 10,
            "redacted": 8,
            "exempt": 1,
            "deleted": 1,
        },
    )

    assert result is True

    assert redaction_run.status == "completed"
    assert redaction_run.page_counts == {
        "original": 10,
        "redacted": 8,
        "exempt": 1,
        "deleted": 1,
    }
    assert redaction_run.completed_at is not None
    assert redaction_run.claim_id is None
    assert redaction_run.lease_expires_at is None
    assert redaction_run.error_message is None

    assert document.status == "redaction_complete"
    assert document.redaction_completed_at is not None
    assert document.error_message is None

    assert session.committed is True


def test_fail_redaction_run_marks_retryable_attempt_for_retry(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        current_redaction_run_id="run-123",
        status="applying_redactions",
        redaction_completed_at=None,
        error_message=None,
    )

    redaction_run = SimpleNamespace(
        run_id="run-123",
        document_id="document-123",
        status="processing",
        claim_id="claim-123",
        lease_expires_at=datetime.now(timezone.utc),
        completed_at=None,
        error_message=None,
    )

    session = FakeRunTransitionSession(
        document=document,
        redaction_run=redaction_run,
    )

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_run_store.fail_redaction_run(
        run_id="run-123",
        claim_id="claim-123",
        error_message="PDF generation failed",
        terminal=False,
    )

    assert result is True

    assert redaction_run.status == "retrying"
    assert redaction_run.error_message == "PDF generation failed"
    assert redaction_run.completed_at is None
    assert redaction_run.claim_id is None
    assert redaction_run.lease_expires_at is None

    assert document.status == "applying_redactions"
    assert document.redaction_completed_at is None
    assert document.error_message is None

    assert session.committed is True


def test_fail_redaction_run_marks_terminal_failure_on_run_and_document(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        current_redaction_run_id="run-123",
        status="applying_redactions",
        redaction_completed_at=None,
        error_message=None,
    )

    redaction_run = SimpleNamespace(
        run_id="run-123",
        document_id="document-123",
        status="processing",
        claim_id="claim-123",
        lease_expires_at=datetime.now(timezone.utc),
        completed_at=None,
        error_message=None,
    )

    session = FakeRunTransitionSession(
        document=document,
        redaction_run=redaction_run,
    )

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_run_store.fail_redaction_run(
        run_id="run-123",
        claim_id="claim-123",
        error_message="PDF generation failed",
        terminal=True,
    )

    assert result is True

    assert redaction_run.status == "failed"
    assert redaction_run.error_message == "PDF generation failed"
    assert redaction_run.completed_at is not None
    assert redaction_run.claim_id is None
    assert redaction_run.lease_expires_at is None

    assert document.status == "redaction_failed"
    assert document.redaction_completed_at is not None
    assert document.error_message == "PDF generation failed"

    assert session.committed is True


def test_complete_redaction_run_rejects_stale_worker(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        current_redaction_run_id="new-run",
        status="applying_redactions",
        redaction_completed_at=None,
        error_message=None,
    )

    redaction_run = SimpleNamespace(
        run_id="run-123",
        document_id="document-123",
        status="processing",
        claim_id="claim-123",
        lease_expires_at=datetime.now(timezone.utc),
        page_counts=None,
        completed_at=None,
        error_message=None,
    )

    session = FakeRunTransitionSession(
        document=document,
        redaction_run=redaction_run,
    )

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_run_store.complete_redaction_run(
        run_id="run-123",
        claim_id="claim-123",
    )

    assert result is False
    assert redaction_run.status == "processing"
    assert document.status == "applying_redactions"
    assert document.current_redaction_run_id == "new-run"
    assert session.committed is False


def test_mark_redaction_run_queued_marks_current_run_queued(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        current_redaction_run_id="run-123",
    )

    redaction_run = SimpleNamespace(
        run_id="run-123",
        document_id="document-123",
        status="enqueueing",
        cancelled_at=None,
        claim_id=None,
        lease_expires_at=None,
    )

    session = FakeRunTransitionSession(
        document=document,
        redaction_run=redaction_run,
    )

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_run_store.mark_redaction_run_queued(
        run_id="run-123",
    )

    assert result is True
    assert redaction_run.status == "queued"
    assert redaction_run.cancelled_at is None
    assert session.committed is True


def test_mark_redaction_run_queued_cancels_superseded_run(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        current_redaction_run_id="new-run",
    )

    redaction_run = SimpleNamespace(
        run_id="run-123",
        document_id="document-123",
        status="enqueueing",
        cancelled_at=None,
        claim_id="old-claim",
        lease_expires_at=datetime.now(timezone.utc),
    )

    session = FakeRunTransitionSession(
        document=document,
        redaction_run=redaction_run,
    )

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_run_store.mark_redaction_run_queued(
        run_id="run-123",
    )

    assert result is False
    assert redaction_run.status == "cancelled"
    assert redaction_run.cancelled_at is not None
    assert redaction_run.claim_id is None
    assert redaction_run.lease_expires_at is None
    assert document.current_redaction_run_id == "new-run"
    assert session.committed is True


def test_fail_redaction_run_enqueue_restores_review_for_current_run(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        current_redaction_run_id="run-123",
        status="applying_redactions",
        redaction_started_at=datetime.now(timezone.utc),
        redaction_completed_at=None,
        error_message=None,
    )

    redaction_run = SimpleNamespace(
        run_id="run-123",
        document_id="document-123",
        status="enqueueing",
        error_message=None,
        completed_at=None,
        claim_id=None,
        lease_expires_at=None,
    )

    session = FakeRunTransitionSession(
        document=document,
        redaction_run=redaction_run,
    )

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_run_store.fail_redaction_run_enqueue(
        run_id="run-123",
        error_message="SQS unavailable",
    )

    assert result is True

    assert redaction_run.status == "failed"
    assert redaction_run.error_message == "SQS unavailable"
    assert redaction_run.completed_at is not None

    assert document.current_redaction_run_id is None
    assert document.status == "ready_for_review"
    assert document.redaction_started_at is None
    assert document.redaction_completed_at is None
    assert document.error_message is None

    assert session.committed is True


def test_claim_redaction_run_rejects_superseded_run(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        current_redaction_run_id="new-run",
        status="applying_redactions",
    )

    redaction_run = SimpleNamespace(
        run_id="run-123",
        document_id="document-123",
        status="queued",
        attempt_count=0,
        claim_id=None,
        lease_expires_at=None,
        started_at=None,
        completed_at=None,
        error_message=None,
    )

    session = FakeRunTransitionSession(
        document=document,
        redaction_run=redaction_run,
    )

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_run_store.claim_redaction_run(
        run_id="run-123",
        claim_id="claim-123",
        attempt_count=1,
        lease_expires_at=datetime.now(timezone.utc),
    )

    assert result is False
    assert redaction_run.status == "queued"
    assert redaction_run.claim_id is None


def test_claim_redaction_run_rejects_processing_run_with_live_lease(
    monkeypatch,
):
    now = datetime.now(timezone.utc)

    document = SimpleNamespace(
        document_id="document-123",
        current_redaction_run_id="run-123",
        status="applying_redactions",
    )

    redaction_run = SimpleNamespace(
        run_id="run-123",
        document_id="document-123",
        status="processing",
        attempt_count=1,
        claim_id="existing-claim",
        lease_expires_at=now.replace(year=now.year + 1),
        started_at=now,
        completed_at=None,
        error_message=None,
    )

    session = FakeRunTransitionSession(
        document=document,
        redaction_run=redaction_run,
    )

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_run_store.claim_redaction_run(
        run_id="run-123",
        claim_id="new-claim",
        attempt_count=2,
        lease_expires_at=now,
    )

    assert result is False
    assert redaction_run.claim_id == "existing-claim"


def test_is_redaction_run_owner_requires_current_document_authority(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        current_redaction_run_id="run-123",
        status="applying_redactions",
    )

    redaction_run = SimpleNamespace(
        run_id="run-123",
        document_id="document-123",
        status="processing",
        claim_id="claim-123",
    )

    class FakeOwnerSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return None

        def get(self, model, object_id):
            if object_id == "run-123":
                return redaction_run

            return document

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: FakeOwnerSession(),
    )

    assert (
        redaction_run_store.is_redaction_run_owner(
            run_id="run-123",
            claim_id="claim-123",
        )
        is True
    )

    document.current_redaction_run_id = "new-run"

    assert (
        redaction_run_store.is_redaction_run_owner(
            run_id="run-123",
            claim_id="claim-123",
        )
        is False
    )


def test_renew_redaction_run_lease_requires_current_owner(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        current_redaction_run_id="run-123",
        status="applying_redactions",
    )

    redaction_run = SimpleNamespace(
        run_id="run-123",
        document_id="document-123",
        status="processing",
        claim_id="claim-123",
        lease_expires_at=None,
    )

    session = FakeRunTransitionSession(
        document=document,
        redaction_run=redaction_run,
    )

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: session,
    )

    new_lease = datetime.now(timezone.utc)

    result = redaction_run_store.renew_redaction_run_lease(
        run_id="run-123",
        claim_id="claim-123",
        lease_expires_at=new_lease,
    )

    assert result is True
    assert redaction_run.lease_expires_at == new_lease
    assert session.committed is True


def test_create_redaction_run_cancels_previous_active_run(
    monkeypatch,
):
    document = SimpleNamespace(
        document_id="document-123",
        current_redaction_run_id="old-run",
        status="applying_redactions",
        redaction_started_at=None,
        redaction_completed_at=None,
        error_message=None,
    )

    decision = SimpleNamespace(
        document_id="document-123",
        revision=4,
        decisions_json={
            "documentId": "document-123",
            "decisions": [{"id": "decision-1"}],
        },
    )

    previous_run = SimpleNamespace(
        run_id="old-run",
        status="processing",
        cancelled_at=None,
        claim_id="old-claim",
        lease_expires_at=datetime.now(timezone.utc),
    )

    session = FakeCreateWithPreviousRunSession(
        document=document,
        decision=decision,
        previous_run=previous_run,
    )

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_run_store.create_redaction_run(
        run_id="new-run",
        document_id="document-123",
        expected_review_revision=4,
    )

    assert result["created"] is True
    assert result["runId"] == "new-run"

    assert previous_run.status == "cancelled"
    assert previous_run.cancelled_at is not None
    assert previous_run.claim_id is None
    assert previous_run.lease_expires_at is None

    assert document.current_redaction_run_id == "new-run"
    assert document.status == "applying_redactions"
    assert session.committed is True
