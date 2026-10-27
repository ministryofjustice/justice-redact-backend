from datetime import datetime, timezone

from app.cli import data_extractor


def test_parse_s3_destination_adds_export_prefix():
    bucket, prefix = data_extractor.parse_s3_destination(
        "s3://alpha-app-justice-redact-dev/"
    )

    assert bucket == "alpha-app-justice-redact-dev"
    assert prefix == "justice-redact-rds"


def test_parse_s3_destination_preserves_existing_prefix():
    bucket, prefix = data_extractor.parse_s3_destination(
        "s3://alpha-app-justice-redact-dev/existing/"
    )

    assert bucket == "alpha-app-justice-redact-dev"
    assert prefix == "existing/justice-redact-rds"


def test_serialise_row_is_deterministic():
    first = {
        "document_id": "document-123",
        "status": "ready_for_review",
        "updated_at": datetime(
            2026,
            10,
            27,
            10,
            0,
            tzinfo=timezone.utc,
        ),
    }

    second = {
        "updated_at": datetime(
            2026,
            10,
            27,
            10,
            0,
            tzinfo=timezone.utc,
        ),
        "status": "ready_for_review",
        "document_id": "document-123",
    }

    assert data_extractor.serialise_row(first) == data_extractor.serialise_row(second)

    assert data_extractor.content_hash(
        data_extractor.serialise_row(first)
    ) == data_extractor.content_hash(data_extractor.serialise_row(second))


def test_upload_row_if_new_uploads_new_content(monkeypatch):
    class FakeS3Client:
        def __init__(self):
            self.put_calls = []

        def put_object(self, **kwargs):
            self.put_calls.append(kwargs)

    s3_client = FakeS3Client()

    monkeypatch.setattr(
        data_extractor,
        "object_exists",
        lambda *args, **kwargs: False,
    )

    row = {
        "document_id": "document-123",
        "revision": 4,
        "decisions_json": {
            "decisions": [],
        },
        "updated_at": datetime(
            2026,
            10,
            27,
            10,
            0,
            tzinfo=timezone.utc,
        ),
    }

    uploaded = data_extractor.upload_row_if_new(
        s3_client,
        bucket="alpha-app-justice-redact-dev",
        export_prefix="justice-redact-rds",
        document_id="document-123",
        table_name="redaction_decisions",
        row=row,
    )

    assert uploaded is True
    assert len(s3_client.put_calls) == 1

    call = s3_client.put_calls[0]

    assert call["Bucket"] == ("alpha-app-justice-redact-dev")

    assert call["Key"].startswith(
        "justice-redact-rds/" "document-123/" "redaction_decisions/" "revision-4-"
    )

    assert call["Key"].endswith(".json")
    assert call["ContentType"] == "application/json"


def test_upload_row_if_new_skips_existing_content(
    monkeypatch,
):
    class FakeS3Client:
        def __init__(self):
            self.put_calls = []

        def put_object(self, **kwargs):
            self.put_calls.append(kwargs)

    s3_client = FakeS3Client()

    monkeypatch.setattr(
        data_extractor,
        "object_exists",
        lambda *args, **kwargs: True,
    )

    uploaded = data_extractor.upload_row_if_new(
        s3_client,
        bucket="alpha-app-justice-redact-dev",
        export_prefix="justice-redact-rds",
        document_id="document-123",
        table_name="documents",
        row={
            "document_id": "document-123",
            "status": "ready_for_review",
        },
    )

    assert uploaded is False
    assert s3_client.put_calls == []


def test_redaction_run_filename_contains_run_id():
    filename = data_extractor.row_filename(
        table_name="redaction_runs",
        row={
            "run_id": "run-456",
        },
        digest="abc123",
    )

    assert filename == "run-456-abc123.json"
