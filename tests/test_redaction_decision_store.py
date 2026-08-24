from datetime import datetime, timezone
from types import SimpleNamespace

from app.services import redaction_decision_store


class FakeSession:
    def __init__(self, decision=None):
        self.decision = decision
        self.added = []
        self.committed = False
        self.executed_statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def get(self, model, document_id):
        return self.decision

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.committed = True

    def execute(self, statement):
        self.executed_statements.append(statement)
        return FakeScalarResult(self.decision)


class FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


def test_save_redaction_decisions_creates_first_revision(
    monkeypatch,
):
    session = FakeSession()

    monkeypatch.setattr(
        redaction_decision_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_decision_store.save_redaction_decisions(
        document_id="document-123",
        decisions_json={
            "documentId": "document-123",
            "decisions": [],
        },
        expected_revision=0,
    )

    assert result["saved"] is True
    assert result["revision"] == 1
    assert len(session.added) == 1
    assert session.added[0].revision == 1
    assert session.added[0].updated_at is not None
    assert session.committed is True


def test_save_redaction_decisions_increments_matching_revision(
    monkeypatch,
):
    decision = SimpleNamespace(
        document_id="document-123",
        decisions_json={
            "documentId": "document-123",
            "decisions": [],
        },
        revision=3,
        updated_at=datetime.now(timezone.utc),
    )

    session = FakeSession(decision)

    monkeypatch.setattr(
        redaction_decision_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_decision_store.save_redaction_decisions(
        document_id="document-123",
        decisions_json={
            "documentId": "document-123",
            "decisions": [{"id": "decision-1"}],
        },
        expected_revision=3,
    )

    assert result["saved"] is True
    assert result["revision"] == 4
    assert decision.revision == 4
    assert session.committed is True


def test_save_redaction_decisions_rejects_stale_revision(
    monkeypatch,
):
    decision = SimpleNamespace(
        document_id="document-123",
        decisions_json={
            "documentId": "document-123",
            "decisions": [],
        },
        revision=5,
        updated_at=datetime.now(timezone.utc),
    )

    session = FakeSession(decision)

    monkeypatch.setattr(
        redaction_decision_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_decision_store.save_redaction_decisions(
        document_id="document-123",
        decisions_json={
            "documentId": "document-123",
            "decisions": [{"id": "stale-change"}],
        },
        expected_revision=4,
    )

    assert result == {
        "saved": False,
        "revision": 5,
    }
    assert decision.revision == 5
    assert session.committed is False


def test_get_redaction_decision_state_returns_revision_and_decisions(
    monkeypatch,
):
    decision = SimpleNamespace(
        document_id="document-123",
        decisions_json={
            "documentId": "document-123",
            "decisions": [{"id": "decision-1"}],
        },
        revision=4,
        updated_at=datetime.now(timezone.utc),
    )

    session = FakeSession(decision)

    monkeypatch.setattr(
        redaction_decision_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_decision_store.get_redaction_decision_state("document-123")

    assert result["documentId"] == "document-123"
    assert result["revision"] == 4
    assert result["decisions"] == [{"id": "decision-1"}]
    assert result["updatedAt"] is not None


def test_get_redaction_decision_state_returns_initial_empty_state(
    monkeypatch,
):
    session = FakeSession()

    monkeypatch.setattr(
        redaction_decision_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_decision_store.get_redaction_decision_state("document-123")

    assert result == {
        "documentId": "document-123",
        "revision": 0,
        "decisions": [],
        "updatedAt": None,
    }


def test_save_redaction_decisions_does_not_increment_when_unchanged(
    monkeypatch,
):
    decisions_json = {
        "documentId": "document-123",
        "decisions": [{"id": "decision-1"}],
    }

    decision = SimpleNamespace(
        document_id="document-123",
        decisions_json=decisions_json,
        revision=5,
        updated_at=datetime.now(timezone.utc),
    )

    session = FakeSession(decision)

    monkeypatch.setattr(
        redaction_decision_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_decision_store.save_redaction_decisions(
        document_id="document-123",
        decisions_json=decisions_json,
        expected_revision=5,
    )

    assert result == {
        "saved": True,
        "revision": 5,
    }

    assert decision.revision == 5
    assert session.committed is False


def test_save_redaction_decisions_locks_document_before_decision_row(
    monkeypatch,
):
    session = FakeSession()

    monkeypatch.setattr(
        redaction_decision_store,
        "SessionLocal",
        lambda: session,
    )

    redaction_decision_store.save_redaction_decisions(
        document_id="document-123",
        decisions_json={
            "documentId": "document-123",
            "decisions": [],
        },
        expected_revision=0,
    )

    assert len(session.executed_statements) == 2

    document_lock = str(session.executed_statements[0])
    decision_lookup = str(session.executed_statements[1])

    assert "FROM documents" in document_lock
    assert "FOR UPDATE" in document_lock

    assert "FROM redaction_decisions" in decision_lookup
    assert "FOR UPDATE" in decision_lookup
