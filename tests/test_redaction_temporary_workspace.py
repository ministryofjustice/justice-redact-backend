
import stat
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from justice_redact.pdf_handler.apply.export_security_audit import (
    PDFExportSecurityError,
)

from app.services import redaction_service


@pytest.mark.parametrize(
    "failure_stage",
    [
        None,
        "download",
        "redacted_audit",
        "vetted_audit",
        "exempt_audit",
        "cancel",
        "upload_redacted",
        "upload_vetted",
        "upload_exempt",
    ],
)
def test_private_pdf_workspace_is_cleaned(
    tmp_path,
    monkeypatch,
    failure_stage,
):
    workspaces = []
    uploaded_keys = []

    real_tempdir = tempfile.TemporaryDirectory

    def tracked_tempdir(*args, **kwargs):
        assert kwargs["prefix"] == ".jr-redaction-"
        assert kwargs["dir"] == "/tmp"

        kwargs["dir"] = str(tmp_path)

        directory = real_tempdir(*args, **kwargs)
        workspaces.append(Path(directory.name))

        assert stat.S_IMODE(
            Path(directory.name).stat().st_mode
        ) == 0o700

        return directory

    monkeypatch.setattr(
        redaction_service,
        "TemporaryDirectory",
        tracked_tempdir,
    )

    monkeypatch.setattr(
        redaction_service,
        "get_document_or_404",
        lambda document_id: {
            "filename": "source.pdf",
        },
    )

    monkeypatch.setattr(
        redaction_service,
        "get_review_result",
        lambda document_id: {"findings": []},
    )

    monkeypatch.setattr(
        redaction_service,
        "build_ai_pdf_handler_decisions",
        lambda **kwargs: [],
    )

    def download_original(key, destination):
        destination = Path(destination)

        assert destination.parent == workspaces[0]
        destination.write_bytes(b"SYNTHETIC_SOURCE")

        if failure_stage == "download":
            raise OSError("Synthetic download failure")

    monkeypatch.setattr(
        redaction_service,
        "download_file_from_s3",
        download_original,
    )

    monkeypatch.setattr(
        redaction_service,
        "download_json_from_s3",
        lambda key: {
            "chunks": [],
            "totalPages": 1,
        },
    )

    monkeypatch.setattr(
        redaction_service,
        "build_pdf_handler_decisions",
        lambda **kwargs: [
            SimpleNamespace(
                kind="text",
                source="manual",
            )
        ],
    )

    monkeypatch.setattr(
        redaction_service,
        "group_decisions_by_chunk",
        lambda **kwargs: {},
    )

    monkeypatch.setattr(
        redaction_service,
        "build_page_decisions",
        lambda decisions: {
            "exempt_page_numbers": [1],
            "deleted_page_numbers": [],
        },
    )

    def mock_exporter(kind):
        def generate(**kwargs):
            output = Path(kwargs["output_path"])

            assert output.parent == workspaces[0]

            output.write_bytes(
                f"SYNTHETIC_{kind}".encode()
            )

            if failure_stage == f"{kind}_audit":
                raise PDFExportSecurityError(
                    "Synthetic audit rejection"
                )

        return generate

    monkeypatch.setattr(
        redaction_service,
        "apply_pdf_decisions",
        mock_exporter("redacted"),
    )

    monkeypatch.setattr(
        redaction_service,
        "apply_vetted_pdf_highlights",
        mock_exporter("vetted"),
    )

    monkeypatch.setattr(
        redaction_service,
        "create_exempt_pdf",
        mock_exporter("exempt"),
    )

    def upload(source, key):
        assert Path(source).is_file()
        assert Path(source).parent == workspaces[0]
        assert "/claims/claim-123/" in key

        uploaded_keys.append(key)

        if key.endswith("/redacted.pdf"):
            kind = "redacted"
        elif key.endswith("/vetted.pdf"):
            kind = "vetted"
        elif key.endswith("/_exempt.pdf"):
            kind = "exempt"
        else:
            raise AssertionError(key)

        if failure_stage == f"upload_{kind}":
            raise OSError("Synthetic upload failure")

    monkeypatch.setattr(
        redaction_service,
        "upload_file_to_s3",
        upload,
    )

    def progress(progress_value):
        if (
            failure_stage == "cancel"
            and progress_value == 55
        ):
            raise (
                redaction_service.RedactionProcessingCancelled(
                    "Synthetic cancellation"
                )
            )

    def run():
        return redaction_service.apply_redactions_for_document(
            document_id="document-123",
            run_id="run-123",
            claim_id="claim-123",
            request=SimpleNamespace(
                decisions=[
                    SimpleNamespace(kind="text")
                ],
            ),
            is_redaction_active=lambda: True,
            progress_callback=progress,
        )

    if failure_stage is None:
        result = run()

        assert len(uploaded_keys) == 3
        assert result["exportPath"] == uploaded_keys[0]
        assert result["vettedExportPath"] == uploaded_keys[1]
        assert result["exemptExportPath"] == uploaded_keys[2]

    elif failure_stage.endswith("_audit"):
        with pytest.raises(
            PDFExportSecurityError,
            match="Synthetic audit rejection",
        ):
            run()

        assert uploaded_keys == []

    elif failure_stage == "cancel":
        with pytest.raises(
            redaction_service.RedactionProcessingCancelled,
            match="Synthetic cancellation",
        ):
            run()

        assert uploaded_keys == []

    else:
        with pytest.raises(
            OSError,
            match="Synthetic",
        ):
            run()

        if failure_stage == "download":
            assert uploaded_keys == []

    assert len(workspaces) == 1
    assert not workspaces[0].exists()
    assert not list(
        tmp_path.glob(".jr-redaction-*")
    )
