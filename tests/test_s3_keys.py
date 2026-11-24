from app.services.s3_keys import (
    document_prefix,
    document_review_chunk_key,
    document_review_manifest_key,
    document_review_search_chunk_key,
    redaction_run_exempt_pdf_key,
    redaction_run_prefix,
    redaction_run_redacted_pdf_key,
    redaction_run_vetted_pdf_key,
)


def test_document_prefix_returns_document_scoped_prefix():
    assert document_prefix("document-123") == "documents/document-123/"


def test_redaction_run_prefix_is_scoped_to_document_and_run():
    assert (
        redaction_run_prefix(
            "document-123",
            "run-456",
        )
        == "documents/document-123/redaction-runs/run-456/"
    )


def test_redaction_run_export_keys_are_run_scoped():
    assert redaction_run_redacted_pdf_key(
        "document-123",
        "run-456",
    ) == ("documents/document-123/redaction-runs/" "run-456/exports/redacted.pdf")

    assert redaction_run_vetted_pdf_key(
        "document-123",
        "run-456",
    ) == ("documents/document-123/redaction-runs/" "run-456/exports/vetted.pdf")

    assert redaction_run_exempt_pdf_key(
        "document-123",
        "run-456",
    ) == ("documents/document-123/redaction-runs/" "run-456/exports/_exempt.pdf")


def test_document_review_manifest_key_is_document_scoped():
    assert (
        document_review_manifest_key("document-123")
        == "documents/document-123/review/manifest.json"
    )


def test_document_review_chunk_key_is_document_and_chunk_scoped():
    assert (
        document_review_chunk_key(
            "document-123",
            3,
        )
        == "documents/document-123/review/chunks/0003.json"
    )


def test_document_review_search_chunk_key_is_document_and_chunk_scoped():
    assert (
        document_review_search_chunk_key(
            "document-123",
            12,
        )
        == "documents/document-123/review/search/0012.json"
    )
