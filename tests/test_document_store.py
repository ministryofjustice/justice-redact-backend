import pytest
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    sessionmaker,
)

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


class ProgressTestBase(DeclarativeBase):
    pass


class ProgressTestDocument(ProgressTestBase):
    __tablename__ = "documents"

    document_id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
    )

    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    processing_job_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    processing_claim_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    processing_progress: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )


def install_progress_test_store(
    monkeypatch,
    *,
    status: str = "processing",
    job_id: str = "job-123",
    claim_id: str | None = "claim-123",
    progress: int = 0,
):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
    )

    ProgressTestBase.metadata.create_all(engine)

    test_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    with test_session_local() as session:
        session.add(
            ProgressTestDocument(
                document_id="document-123",
                status=status,
                processing_job_id=job_id,
                processing_claim_id=claim_id,
                processing_progress=progress,
            )
        )
        session.commit()

    monkeypatch.setattr(
        document_store,
        "Document",
        ProgressTestDocument,
    )

    monkeypatch.setattr(
        document_store,
        "SessionLocal",
        test_session_local,
    )

    return test_session_local


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

    assert (
        document_store.is_document_processing_owner(
            document_id="document-123",
            job_id="job-123",
            claim_id="claim-123",
        )
        is True
    )


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

    assert (
        document_store.is_document_processing_owner(
            document_id="document-123",
            job_id="job-123",
            claim_id="claim-123",
        )
        is False
    )


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

    assert (
        document_store.is_document_processing_owner(
            document_id="document-123",
            job_id="job-123",
            claim_id="old-claim",
        )
        is False
    )


def test_is_document_processing_owner_returns_false_when_document_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        document_store,
        "SessionLocal",
        lambda: FakeSession(None),
    )

    assert (
        document_store.is_document_processing_owner(
            document_id="document-123",
            job_id="job-123",
            claim_id="claim-123",
        )
        is False
    )


def test_update_document_processing_progress_advances_for_current_owner(
    monkeypatch,
):
    test_session_local = install_progress_test_store(
        monkeypatch,
        progress=20,
    )

    updated = document_store.update_document_processing_progress(
        document_id="document-123",
        job_id="job-123",
        claim_id="claim-123",
        progress=40,
    )

    assert updated is True

    with test_session_local() as session:
        document = session.get(
            ProgressTestDocument,
            "document-123",
        )

        assert document.processing_progress == 40


def test_update_document_processing_progress_does_not_go_backwards(
    monkeypatch,
):
    test_session_local = install_progress_test_store(
        monkeypatch,
        progress=60,
    )

    updated = document_store.update_document_processing_progress(
        document_id="document-123",
        job_id="job-123",
        claim_id="claim-123",
        progress=40,
    )

    assert updated is True

    with test_session_local() as session:
        document = session.get(
            ProgressTestDocument,
            "document-123",
        )

        assert document.processing_progress == 60


def test_update_document_processing_progress_allows_same_high_water_mark(
    monkeypatch,
):
    test_session_local = install_progress_test_store(
        monkeypatch,
        progress=60,
    )

    updated = document_store.update_document_processing_progress(
        document_id="document-123",
        job_id="job-123",
        claim_id="claim-123",
        progress=60,
    )

    assert updated is True

    with test_session_local() as session:
        document = session.get(
            ProgressTestDocument,
            "document-123",
        )

        assert document.processing_progress == 60


@pytest.mark.parametrize(
    ("job_id", "claim_id", "status"),
    [
        ("wrong-job", "claim-123", "processing"),
        ("job-123", "wrong-claim", "processing"),
        ("job-123", "claim-123", "retrying"),
    ],
)
def test_update_document_processing_progress_rejects_non_owner(
    monkeypatch,
    job_id,
    claim_id,
    status,
):
    test_session_local = install_progress_test_store(
        monkeypatch,
        status=status,
        progress=25,
    )

    updated = document_store.update_document_processing_progress(
        document_id="document-123",
        job_id=job_id,
        claim_id=claim_id,
        progress=50,
    )

    assert updated is False

    with test_session_local() as session:
        document = session.get(
            ProgressTestDocument,
            "document-123",
        )

        assert document.processing_progress == 25


def test_update_document_processing_progress_allows_99(
    monkeypatch,
):
    test_session_local = install_progress_test_store(
        monkeypatch,
    )

    updated = document_store.update_document_processing_progress(
        document_id="document-123",
        job_id="job-123",
        claim_id="claim-123",
        progress=99,
    )

    assert updated is True

    with test_session_local() as session:
        document = session.get(
            ProgressTestDocument,
            "document-123",
        )

        assert document.processing_progress == 99


@pytest.mark.parametrize(
    "progress",
    [
        -1,
        100,
        101,
    ],
)
def test_update_document_processing_progress_rejects_out_of_range(
    monkeypatch,
    progress,
):
    install_progress_test_store(
        monkeypatch,
    )

    with pytest.raises(
        ValueError,
        match="Processing progress must be between 0 and 99",
    ):
        document_store.update_document_processing_progress(
            document_id="document-123",
            job_id="job-123",
            claim_id="claim-123",
            progress=progress,
        )


class OwnershipTestBase(DeclarativeBase):
    pass


class OwnershipTestDocument(OwnershipTestBase):
    __tablename__ = "owned_documents"

    document_id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
    )

    owner_user_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    filename: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    document_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    warning_reason: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    subject_name: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="",
    )

    subject_prison_number: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="",
    )

    other_phrases: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(
            timezone.utc,
        ),
    )


def install_ownership_test_store(
    monkeypatch,
):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
    )

    OwnershipTestBase.metadata.create_all(engine)

    test_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    monkeypatch.setattr(
        document_store,
        "Document",
        OwnershipTestDocument,
    )

    monkeypatch.setattr(
        document_store,
        "SessionLocal",
        test_session_local,
    )

    monkeypatch.setattr(
        document_store,
        "document_to_dict",
        lambda document: {
            "documentId": document.document_id,
            "filename": document.filename,
        },
    )

    return test_session_local


def test_create_document_record_assigns_owner(
    monkeypatch,
):
    test_session_local = install_ownership_test_store(
        monkeypatch,
    )

    result = document_store.create_document_record(
        document_id="document-123",
        owner_user_id="user-123",
        filename="example.pdf",
        document_type="nomis",
    )

    assert result == {
        "documentId": "document-123",
        "filename": "example.pdf",
    }

    with test_session_local() as session:
        document = session.get(
            OwnershipTestDocument,
            "document-123",
        )

        assert document is not None
        assert document.owner_user_id == "user-123"


def test_get_document_for_user_returns_owned_document(
    monkeypatch,
):
    test_session_local = install_ownership_test_store(
        monkeypatch,
    )

    with test_session_local() as session:
        session.add(
            OwnershipTestDocument(
                document_id="document-123",
                owner_user_id="user-123",
                filename="example.pdf",
                status="uploaded",
                document_type="nomis",
                subject_name="",
                subject_prison_number="",
                other_phrases="",
            )
        )

        session.commit()

    result = document_store.get_document_for_user_or_404(
        "document-123",
        "user-123",
    )

    assert result["documentId"] == "document-123"


def test_get_document_for_user_returns_404_for_other_user(
    monkeypatch,
):
    test_session_local = install_ownership_test_store(
        monkeypatch,
    )

    with test_session_local() as session:
        session.add(
            OwnershipTestDocument(
                document_id="document-123",
                owner_user_id="user-a",
                filename="example.pdf",
                status="uploaded",
                document_type="nomis",
                subject_name="",
                subject_prison_number="",
                other_phrases="",
            )
        )

        session.commit()

    with pytest.raises(document_store.HTTPException) as exc_info:
        document_store.get_document_for_user_or_404(
            "document-123",
            "user-b",
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Document not found"


def test_get_document_for_user_returns_404_for_unowned_legacy_document(
    monkeypatch,
):
    test_session_local = install_ownership_test_store(
        monkeypatch,
    )

    with test_session_local() as session:
        session.add(
            OwnershipTestDocument(
                document_id="legacy-document",
                owner_user_id=None,
                filename="legacy.pdf",
                status="uploaded",
                document_type="nomis",
                subject_name="",
                subject_prison_number="",
                other_phrases="",
            )
        )

        session.commit()

    with pytest.raises(document_store.HTTPException) as exc_info:
        document_store.get_document_for_user_or_404(
            "legacy-document",
            "user-123",
        )

    assert exc_info.value.status_code == 404


def test_get_document_for_user_allows_document_younger_than_30_days(
    monkeypatch,
):
    test_session_local = install_ownership_test_store(
        monkeypatch,
    )

    with test_session_local() as session:
        session.add(
            OwnershipTestDocument(
                document_id="document-123",
                owner_user_id="user-123",
                filename="example.pdf",
                status="ready_for_review",
                document_type="nomis",
                subject_name="",
                subject_prison_number="",
                other_phrases="",
                created_at=(
                    datetime.now(timezone.utc)
                    - timedelta(
                        days=29,
                        hours=23,
                    )
                ),
            )
        )

        session.commit()

    result = document_store.get_document_for_user_or_404(
        "document-123",
        "user-123",
    )

    assert result["documentId"] == "document-123"


def test_get_document_for_user_returns_410_at_30_days(
    monkeypatch,
):
    test_session_local = install_ownership_test_store(
        monkeypatch,
    )

    with test_session_local() as session:
        session.add(
            OwnershipTestDocument(
                document_id="document-123",
                owner_user_id="user-123",
                filename="example.pdf",
                status="ready_for_review",
                document_type="nomis",
                subject_name="",
                subject_prison_number="",
                other_phrases="",
                created_at=(datetime.now(timezone.utc) - timedelta(days=30)),
            )
        )

        session.commit()

    with pytest.raises(
        document_store.HTTPException,
    ) as exc_info:
        document_store.get_document_for_user_or_404(
            "document-123",
            "user-123",
        )

    assert exc_info.value.status_code == 410
    assert exc_info.value.detail == "Document link expired"


def test_get_document_for_user_checks_ownership_before_expiry(
    monkeypatch,
):
    test_session_local = install_ownership_test_store(
        monkeypatch,
    )

    with test_session_local() as session:
        session.add(
            OwnershipTestDocument(
                document_id="document-123",
                owner_user_id="user-a",
                filename="example.pdf",
                status="ready_for_review",
                document_type="nomis",
                subject_name="",
                subject_prison_number="",
                other_phrases="",
                created_at=(datetime.now(timezone.utc) - timedelta(days=31)),
            )
        )

        session.commit()

    with pytest.raises(
        document_store.HTTPException,
    ) as exc_info:
        document_store.get_document_for_user_or_404(
            "document-123",
            "user-b",
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Document not found"


class NotificationTestBase(DeclarativeBase):
    pass


class NotificationTestUser(NotificationTestBase):
    __tablename__ = "notification_users"

    user_id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
    )

    email: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )


class NotificationTestDocument(NotificationTestBase):
    __tablename__ = "notification_documents"

    document_id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
    )

    filename: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    owner_user_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    ready_notification_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


def install_notification_test_store(
    monkeypatch,
    *,
    status: str = "ready_for_review",
    sent_at: datetime | None = None,
):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
    )

    NotificationTestBase.metadata.create_all(engine)

    test_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    with test_session_local() as session:
        session.add(
            NotificationTestUser(
                user_id="user-123",
                email="user@justice.gov.uk",
            )
        )

        session.add(
            NotificationTestDocument(
                document_id="document-123",
                filename="example.pdf",
                owner_user_id="user-123",
                status=status,
                ready_notification_sent_at=sent_at,
            )
        )

        session.commit()

    monkeypatch.setattr(
        document_store,
        "User",
        NotificationTestUser,
    )

    monkeypatch.setattr(
        document_store,
        "Document",
        NotificationTestDocument,
    )

    monkeypatch.setattr(
        document_store,
        "SessionLocal",
        test_session_local,
    )

    return test_session_local


def test_get_pending_ready_notification_returns_owner_email_and_filename(
    monkeypatch,
):
    install_notification_test_store(
        monkeypatch,
    )

    result = document_store.get_pending_ready_notification(
        "document-123",
    )

    assert result == {
        "email": "user@justice.gov.uk",
        "filename": "example.pdf",
    }


def test_get_pending_ready_notification_requires_ready_document(
    monkeypatch,
):
    install_notification_test_store(
        monkeypatch,
        status="processing",
    )

    result = document_store.get_pending_ready_notification(
        "document-123",
    )

    assert result is None


def test_get_pending_ready_notification_ignores_already_sent(
    monkeypatch,
):
    install_notification_test_store(
        monkeypatch,
        sent_at=datetime(
            2026,
            9,
            30,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    )

    result = document_store.get_pending_ready_notification(
        "document-123",
    )

    assert result is None


def test_mark_ready_notification_sent_only_marks_once(
    monkeypatch,
):
    test_session_local = install_notification_test_store(
        monkeypatch,
    )

    sent_at = datetime(
        2026,
        9,
        30,
        12,
        0,
        tzinfo=timezone.utc,
    )

    first_result = document_store.mark_ready_notification_sent(
        document_id="document-123",
        sent_at=sent_at,
    )

    second_result = document_store.mark_ready_notification_sent(
        document_id="document-123",
        sent_at=sent_at,
    )

    assert first_result is True
    assert second_result is False

    with test_session_local() as session:
        document = session.get(
            NotificationTestDocument,
            "document-123",
        )

        assert document.ready_notification_sent_at == sent_at.replace(tzinfo=None)
