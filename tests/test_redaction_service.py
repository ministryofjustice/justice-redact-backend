import pytest

from app.services import redaction_service
from types import SimpleNamespace


def test_calculate_redaction_stage_progress_maps_stage_boundaries():
    calculate = redaction_service.calculate_redaction_stage_progress

    assert (
        calculate(
            start_progress=5,
            end_progress=25,
            completed=0,
            total=4,
        )
        == 5
    )

    assert (
        calculate(
            start_progress=5,
            end_progress=25,
            completed=2,
            total=4,
        )
        == 15
    )

    assert (
        calculate(
            start_progress=5,
            end_progress=25,
            completed=4,
            total=4,
        )
        == 25
    )


def test_calculate_redaction_stage_progress_floors_fractional_progress():
    progress = redaction_service.calculate_redaction_stage_progress(
        start_progress=90,
        end_progress=98,
        completed=1,
        total=3,
    )

    assert progress == 92


@pytest.mark.parametrize(
    (
        "start_progress",
        "end_progress",
    ),
    [
        (-1, 10),
        (10, 100),
        (50, 40),
    ],
)
def test_calculate_redaction_stage_progress_rejects_invalid_range(
    start_progress,
    end_progress,
):
    with pytest.raises(
        ValueError,
        match="Invalid redaction progress range",
    ):
        redaction_service.calculate_redaction_stage_progress(
            start_progress=start_progress,
            end_progress=end_progress,
            completed=1,
            total=1,
        )


@pytest.mark.parametrize(
    (
        "completed",
        "total",
        "message",
    ),
    [
        (0, 0, "Progress total must be greater than 0"),
        (-1, 2, "Progress completed must be between 0 and total"),
        (3, 2, "Progress completed must be between 0 and total"),
    ],
)
def test_calculate_redaction_stage_progress_rejects_invalid_counts(
    completed,
    total,
    message,
):
    with pytest.raises(
        ValueError,
        match=message,
    ):
        redaction_service.calculate_redaction_stage_progress(
            start_progress=5,
            end_progress=25,
            completed=completed,
            total=total,
        )


def test_apply_redactions_reports_progress_for_two_export_path(
    monkeypatch,
):
    progress_updates = []
    upload_calls = []

    request = SimpleNamespace(
        decisions=[
            SimpleNamespace(
                kind="image",
            )
        ],
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
        lambda document_id: {
            "findings": [],
        },
    )

    monkeypatch.setattr(
        redaction_service,
        "download_file_from_s3",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        redaction_service,
        "download_json_from_s3",
        lambda key: {
            "totalPages": 3,
            "chunks": [],
        },
    )

    monkeypatch.setattr(
        redaction_service,
        "build_pdf_handler_decisions",
        lambda **kwargs: [
            SimpleNamespace(),
        ],
    )

    monkeypatch.setattr(
        redaction_service,
        "build_ai_pdf_handler_decisions",
        lambda **kwargs: [],
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
            "exempt_page_numbers": [],
            "deleted_page_numbers": [],
        },
    )

    def fake_apply_pdf_decisions(**kwargs):
        progress_callback = kwargs["progress_callback"]

        progress_callback(1, 2)
        progress_callback(2, 2)

    monkeypatch.setattr(
        redaction_service,
        "apply_pdf_decisions",
        fake_apply_pdf_decisions,
    )

    def fake_apply_vetted_pdf_highlights(**kwargs):
        progress_callback = kwargs["progress_callback"]

        progress_callback(1, 2)
        progress_callback(2, 2)

    monkeypatch.setattr(
        redaction_service,
        "apply_vetted_pdf_highlights",
        fake_apply_vetted_pdf_highlights,
    )

    monkeypatch.setattr(
        redaction_service,
        "upload_file_to_s3",
        lambda source_path, key: upload_calls.append(
            (
                source_path,
                key,
            )
        ),
    )

    result = redaction_service.apply_redactions_for_document(
        document_id="document-123",
        run_id="run-123",
        request=request,
        is_redaction_active=lambda: True,
        progress_callback=progress_updates.append,
    )

    assert progress_updates == [
        1,
        5,
        25,
        39,
        54,
        55,
        67,
        79,
        80,
        90,
        94,
        98,
        99,
    ]

    assert 100 not in progress_updates

    assert len(upload_calls) == 2

    assert result["pageCounts"] == {
        "original": 3,
        "exempt": 0,
        "deleted": 0,
        "redacted": 3,
    }

    assert result["exemptExportPath"] is None


def test_apply_redactions_reports_progress_for_three_export_path(
    monkeypatch,
):
    progress_updates = []
    upload_calls = []

    request = SimpleNamespace(
        decisions=[
            SimpleNamespace(
                kind="page",
            )
        ],
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
        lambda document_id: {
            "findings": [],
        },
    )

    monkeypatch.setattr(
        redaction_service,
        "download_file_from_s3",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        redaction_service,
        "download_json_from_s3",
        lambda key: {
            "totalPages": 3,
            "chunks": [],
        },
    )

    monkeypatch.setattr(
        redaction_service,
        "build_pdf_handler_decisions",
        lambda **kwargs: [],
    )

    monkeypatch.setattr(
        redaction_service,
        "build_ai_pdf_handler_decisions",
        lambda **kwargs: [],
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
            "exempt_page_numbers": [2],
            "deleted_page_numbers": [],
        },
    )

    def fake_apply_pdf_decisions(**kwargs):
        progress_callback = kwargs["progress_callback"]

        progress_callback(1, 2)
        progress_callback(2, 2)

    monkeypatch.setattr(
        redaction_service,
        "apply_pdf_decisions",
        fake_apply_pdf_decisions,
    )

    def fake_apply_vetted_pdf_highlights(**kwargs):
        progress_callback = kwargs["progress_callback"]

        progress_callback(1, 2)
        progress_callback(2, 2)

    monkeypatch.setattr(
        redaction_service,
        "apply_vetted_pdf_highlights",
        fake_apply_vetted_pdf_highlights,
    )

    def fake_create_exempt_pdf(**kwargs):
        progress_callback = kwargs["progress_callback"]

        progress_callback(1, 2)
        progress_callback(2, 2)

    monkeypatch.setattr(
        redaction_service,
        "create_exempt_pdf",
        fake_create_exempt_pdf,
    )

    monkeypatch.setattr(
        redaction_service,
        "upload_file_to_s3",
        lambda source_path, key: upload_calls.append(
            (
                source_path,
                key,
            )
        ),
    )

    result = redaction_service.apply_redactions_for_document(
        document_id="document-123",
        run_id="run-123",
        request=request,
        is_redaction_active=lambda: True,
        progress_callback=progress_updates.append,
    )

    assert progress_updates == [
        1,
        5,
        25,
        39,
        54,
        55,
        67,
        79,
        80,
        84,
        89,
        90,
        92,
        95,
        98,
        99,
    ]

    assert 100 not in progress_updates

    assert len(upload_calls) == 3

    assert result["pageCounts"] == {
        "original": 3,
        "exempt": 1,
        "deleted": 0,
        "redacted": 2,
    }

    assert result["exemptExportPath"] is not None
