import pytest
from types import SimpleNamespace
from sqlalchemy import Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
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
