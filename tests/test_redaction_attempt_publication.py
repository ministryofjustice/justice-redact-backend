
import asyncio
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from app.api.routers import exports
from app.services import redaction_run_store
from app.services.auth_service import AuthenticatedUser
from app.services.s3_keys import (
    redaction_run_exempt_pdf_key,
    redaction_run_redacted_pdf_key,
    redaction_run_vetted_pdf_key,
)


DOCUMENT_ID = "document-123"
RUN_ID = "run-123"
WINNING_CLAIM = "claim-winning"
LOSING_CLAIM = "claim-losing"

CURRENT_USER = AuthenticatedUser(
    user_id="user-123",
    email="user@justice.gov.uk",
)


def _document():
    return {
        "documentId": DOCUMENT_ID,
        "filename": "example.pdf",
        "status": "redaction_complete",
        "currentRedactionRunId": RUN_ID,
    }


def _completed_run(published_claim_id):
    return {
        "runId": RUN_ID,
        "documentId": DOCUMENT_ID,
        "status": "completed",
        "publishedClaimId": published_claim_id,
        "pageCounts": {
            "original": 10,
            "redacted": 8,
            "exempt": 1,
            "deleted": 1,
        },
    }


def _expected_keys(claim_id):
    return [
        redaction_run_redacted_pdf_key(
            DOCUMENT_ID, RUN_ID, claim_id
        ),
        redaction_run_vetted_pdf_key(
            DOCUMENT_ID, RUN_ID, claim_id
        ),
        redaction_run_exempt_pdf_key(
            DOCUMENT_ID, RUN_ID, claim_id
        ),
    ]


def _mock_export_state(
    monkeypatch,
    published_claim_id,
):
    monkeypatch.setattr(
        exports,
        "get_document_for_user_or_404",
        lambda document_id, user_id: _document(),
    )

    monkeypatch.setattr(
        exports,
        "get_redaction_run",
        lambda run_id: _completed_run(
            published_claim_id
        ),
    )


@pytest.mark.parametrize(
    "key_builder",
    [
        redaction_run_redacted_pdf_key,
        redaction_run_vetted_pdf_key,
        redaction_run_exempt_pdf_key,
    ],
)
def test_separate_claims_have_separate_s3_objects(
    key_builder,
):
    winning = key_builder(
        DOCUMENT_ID,
        RUN_ID,
        WINNING_CLAIM,
    )

    losing = key_builder(
        DOCUMENT_ID,
        RUN_ID,
        LOSING_CLAIM,
    )

    assert winning != losing

    assert (
        f"/claims/{WINNING_CLAIM}/"
        in winning
    )

    assert (
        f"/claims/{LOSING_CLAIM}/"
        in losing
    )


@pytest.mark.parametrize(
    "key_builder",
    [
        redaction_run_redacted_pdf_key,
        redaction_run_vetted_pdf_key,
        redaction_run_exempt_pdf_key,
    ],
)
def test_legacy_s3_keys_remain_unchanged(
    key_builder,
):
    legacy = key_builder(
        DOCUMENT_ID,
        RUN_ID,
    )

    explicit_legacy = key_builder(
        DOCUMENT_ID,
        RUN_ID,
        None,
    )

    assert legacy == explicit_legacy
    assert "/claims/" not in legacy
    assert "/exports/" in legacy


@pytest.mark.parametrize(
    "invalid_claim",
    [
        "",
        "claim/invalid",
        "claim\\invalid",
    ],
)
def test_invalid_claim_id_is_rejected(
    invalid_claim,
):
    with pytest.raises(ValueError):
        redaction_run_redacted_pdf_key(
            DOCUMENT_ID,
            RUN_ID,
            invalid_claim,
        )


@pytest.mark.parametrize(
    "published_claim_id",
    [
        None,
        WINNING_CLAIM,
    ],
)
def test_export_metadata_uses_published_claim(
    monkeypatch,
    published_claim_id,
):
    _mock_export_state(
        monkeypatch,
        published_claim_id,
    )

    requested_keys = []

    def exists(key):
        requested_keys.append(key)
        return True

    monkeypatch.setattr(
        exports,
        "object_exists_in_s3",
        exists,
    )

    result = asyncio.run(
        exports.get_document_export(
            DOCUMENT_ID,
            RUN_ID,
            current_user=CURRENT_USER,
        )
    )

    assert result["status"] == "redaction_complete"

    assert requested_keys == _expected_keys(
        published_claim_id
    )


@pytest.mark.parametrize(
    "published_claim_id",
    [
        None,
        WINNING_CLAIM,
    ],
)
def test_download_all_uses_published_claim(
    monkeypatch,
    published_claim_id,
):
    _mock_export_state(
        monkeypatch,
        published_claim_id,
    )

    monkeypatch.setattr(
        exports,
        "object_exists_in_s3",
        lambda key: True,
    )

    requested_keys = []

    def read_object(key):
        requested_keys.append(key)
        return key.encode()

    monkeypatch.setattr(
        exports,
        "get_object_from_s3",
        read_object,
    )

    response = asyncio.run(
        exports.download_all_files(
            DOCUMENT_ID,
            RUN_ID,
            current_user=CURRENT_USER,
        )
    )

    expected = _expected_keys(
        published_claim_id
    )

    assert requested_keys == expected

    with ZipFile(BytesIO(response.body)) as archive:
        assert archive.read(
            "example_redacted.pdf"
        ) == expected[0].encode()

        assert archive.read(
            "example_vetted.pdf"
        ) == expected[1].encode()

        assert archive.read(
            "example_exempt.pdf"
        ) == expected[2].encode()


@pytest.mark.parametrize(
    "file_kind",
    [
        "redacted",
        "vetted",
        "exempt",
    ],
)
@pytest.mark.parametrize(
    "published_claim_id",
    [
        None,
        WINNING_CLAIM,
    ],
)
def test_individual_download_uses_correct_claim(
    monkeypatch,
    file_kind,
    published_claim_id,
):
    _mock_export_state(
        monkeypatch,
        published_claim_id,
    )

    monkeypatch.setattr(
        exports,
        "object_exists_in_s3",
        lambda key: True,
    )

    requested_keys = []

    def read_object(key):
        requested_keys.append(key)
        return b"PDF_CONTENT"

    monkeypatch.setattr(
        exports,
        "get_object_from_s3",
        read_object,
    )

    route = getattr(
        exports,
        f"download_{file_kind}_file",
    )

    response = asyncio.run(
        route(
            DOCUMENT_ID,
            RUN_ID,
            current_user=CURRENT_USER,
        )
    )

    expected_keys = _expected_keys(
        published_claim_id
    )

    expected_key = dict(
        zip(
            ("redacted", "vetted", "exempt"),
            expected_keys,
        )
    )[file_kind]

    assert requested_keys == [expected_key]
    assert response.body == b"PDF_CONTENT"


def test_older_claim_cannot_replace_published_objects():
    winning = set(
        _expected_keys(WINNING_CLAIM)
    )

    losing = set(
        _expected_keys(LOSING_CLAIM)
    )

    assert winning.isdisjoint(losing)


class FakeTransitionSession:
    def __init__(self, document, run):
        self.document = document
        self.run = run
        self.execute_count = 0
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def get(self, model, run_id):
        return self.run

    def execute(self, statement):
        self.execute_count += 1

        value = (
            self.document
            if self.execute_count == 1
            else self.run
        )

        return SimpleNamespace(
            scalar_one_or_none=lambda: value
        )

    def commit(self):
        self.committed = True


def _transaction_state(
    *,
    document_run_id=RUN_ID,
    document_status="applying_redactions",
    run_status="processing",
    active_claim=WINNING_CLAIM,
):
    document = SimpleNamespace(
        document_id=DOCUMENT_ID,
        current_redaction_run_id=document_run_id,
        status=document_status,
        redaction_completed_at=None,
        error_message=None,
    )

    run = SimpleNamespace(
        run_id=RUN_ID,
        document_id=DOCUMENT_ID,
        status=run_status,
        claim_id=active_claim,
        published_claim_id=None,
        processing_progress=99,
        page_counts=None,
        completed_at=None,
        lease_expires_at=datetime.now(
            timezone.utc
        ),
        error_message=None,
    )

    return document, run


def test_winning_claim_published_in_single_transaction(
    monkeypatch,
):
    document, run = _transaction_state()

    session = FakeTransitionSession(
        document,
        run,
    )

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: session,
    )

    page_counts = {
        "original": 10,
        "redacted": 8,
        "exempt": 1,
        "deleted": 1,
    }

    result = redaction_run_store.complete_redaction_run(
        run_id=RUN_ID,
        claim_id=WINNING_CLAIM,
        page_counts=page_counts,
    )

    assert result is True
    assert session.committed is True

    assert run.published_claim_id == WINNING_CLAIM
    assert run.status == "completed"
    assert run.processing_progress == 100
    assert run.page_counts == page_counts
    assert run.claim_id is None

    assert document.status == "redaction_complete"


@pytest.mark.parametrize(
    "document_run_id,document_status,run_status,active_claim",
    [
        (
            RUN_ID,
            "applying_redactions",
            "processing",
            WINNING_CLAIM,
        ),
        (
            "newer-run",
            "applying_redactions",
            "processing",
            LOSING_CLAIM,
        ),
        (
            RUN_ID,
            "redaction_complete",
            "processing",
            LOSING_CLAIM,
        ),
        (
            RUN_ID,
            "applying_redactions",
            "completed",
            LOSING_CLAIM,
        ),
    ],
)
def test_stale_claim_cannot_complete_run(
    monkeypatch,
    document_run_id,
    document_status,
    run_status,
    active_claim,
):
    document, run = _transaction_state(
        document_run_id=document_run_id,
        document_status=document_status,
        run_status=run_status,
        active_claim=active_claim,
    )

    session = FakeTransitionSession(
        document,
        run,
    )

    monkeypatch.setattr(
        redaction_run_store,
        "SessionLocal",
        lambda: session,
    )

    result = redaction_run_store.complete_redaction_run(
        run_id=RUN_ID,
        claim_id=LOSING_CLAIM,
        page_counts={"original": 10},
    )

    assert result is False
    assert session.committed is False

    assert run.published_claim_id is None
    assert run.status == run_status

    assert document.status == document_status
    assert (
        document.current_redaction_run_id
        == document_run_id
    )
