from types import SimpleNamespace

import pytest

from app.models.redaction_models import (
    ApplyRedactionsRequest,
    TextRedactionDecision,
)
from app.services import redaction_service
from app.services.redaction_integrity import (
    RedactionIntegrityError,
    assert_manual_chunk_coverage,
    assert_manual_conversion_complete,
    assert_manual_resolution_complete,
    assert_page_decisions_valid,
)


def decision(page, kind="text"):
    return SimpleNamespace(
        kind=kind,
        page_number=page,
        source="manual",
        action="redact",
        item_id=f"item-{page}" if kind == "text" else None,
    )


def context():
    return {
        "document_id": "document-1",
        "run_id": "run-1",
        "claim_id": "claim-1",
    }


def test_manual_decisions_resolve_across_two_chunks():
    first = decision(1)
    second = decision(101)

    groups = {
        0: [first],
        1: [second],
    }

    assert_manual_chunk_coverage(
        requested_decisions=[first, second],
        decisions_by_chunk=groups,
        **context(),
    )

    assert_manual_resolution_complete(
        requested_decisions=[first, second],
        resolved_decisions=[
            (
                first,
                SimpleNamespace(
                    page_number=1,
                    boxes=[object()],
                ),
            ),
            (
                second,
                SimpleNamespace(
                    page_number=101,
                    boxes=[object()],
                ),
            ),
        ],
        **context(),
    )


@pytest.mark.parametrize(
    "problem,code",
    [
        ("missing", "UNRESOLVED_MANUAL_DECISION"),
        (
            "duplicate",
            "DUPLICATE_MANUAL_DECISION_RESOLUTION",
        ),
        (
            "wrong_page",
            "MANUAL_RESOLUTION_PAGE_MISMATCH",
        ),
        (
            "no_boxes",
            "MANUAL_RESOLUTION_HAS_NO_BOXES",
        ),
    ],
)
def test_resolution_failure_is_fatal(problem, code):
    original = decision(2)

    resolved = SimpleNamespace(
        page_number=2,
        boxes=[object()],
    )

    decisions = [(original, resolved)]

    if problem == "missing":
        decisions = []

    if problem == "duplicate":
        decisions.append((original, resolved))

    if problem == "wrong_page":
        resolved.page_number = 5

    if problem == "no_boxes":
        resolved.boxes = []

    with pytest.raises(
        RedactionIntegrityError,
        match=code,
    ):
        assert_manual_resolution_complete(
            requested_decisions=[original],
            resolved_decisions=decisions,
            **context(),
        )


def test_unassigned_decision_fails_chunk_coverage():
    with pytest.raises(
        RedactionIntegrityError,
        match="MANUAL_DECISION_WITHOUT_GEOMETRY_CHUNK",
    ):
        assert_manual_chunk_coverage(
            requested_decisions=[decision(201)],
            decisions_by_chunk={0: []},
            **context(),
        )


def test_unexpected_conversion_fails():
    with pytest.raises(
        RedactionIntegrityError,
        match="MANUAL_DECISION_NOT_CONVERTED",
    ):
        assert_manual_conversion_complete(
            request_decisions=[
                SimpleNamespace(
                    kind="text",
                    pageNumber=1,
                    itemId="first",
                    start=0,
                    end=4,
                    source="manual",
                    action="redact",
                ),
            ],
            converted_decisions=[],
            **context(),
        )


def test_failed_chunk_assignment_prevents_exports(monkeypatch):
    decision_input = TextRedactionDecision(
        kind="text",
        pageNumber=1,
        itemId="item-1",
        start=0,
        end=4,
        text="FAKE",
        action="redact",
        source="manual",
    )

    request = ApplyRedactionsRequest(
        documentId="document-1",
        decisions=[decision_input],
        expectedRevision=0,
    )

    monkeypatch.setattr(
        redaction_service,
        "get_document_or_404",
        lambda document_id: {"filename": "synthetic.pdf"},
    )

    monkeypatch.setattr(
        redaction_service,
        "get_review_result",
        lambda document_id: {"findings": []},
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
            "totalPages": 1,
            "chunks": [],
        },
    )

    uploads = []

    monkeypatch.setattr(
        redaction_service,
        "upload_file_to_s3",
        lambda *args, **kwargs: uploads.append(
            (args, kwargs)
        ),
    )

    monkeypatch.setattr(
        redaction_service,
        "apply_pdf_decisions",
        lambda **kwargs: pytest.fail(
            "No PDF should be generated"
        ),
    )

    with pytest.raises(
        RedactionIntegrityError,
        match="MANUAL_DECISION_WITHOUT_GEOMETRY_CHUNK",
    ):
        redaction_service.apply_redactions_for_document(
            document_id="document-1",
            run_id="run-1",
            claim_id="claim-1",
            request=request,
            is_redaction_active=lambda: True,
        )

    assert uploads == []


@pytest.mark.parametrize(
    "resolved",
    [
        SimpleNamespace(page_number=2),
        SimpleNamespace(page_number=2, boxes=None),
        SimpleNamespace(page_number=2, precise_boxes=[]),
        SimpleNamespace(page_number=2, line_boxes=[]),
        SimpleNamespace(
            page_number=2,
            boxes=[],
            merged_bbox=object(),
        ),
    ],
)
def test_missing_exportable_geometry_fails_closed(resolved):
    original = decision(2)

    with pytest.raises(
        RedactionIntegrityError,
        match="MANUAL_RESOLUTION_HAS_NO_BOXES",
    ):
        assert_manual_resolution_complete(
            requested_decisions=[original],
            resolved_decisions=[(original, resolved)],
            **context(),
        )


def test_precise_only_geometry_is_accepted():
    original = decision(2)

    assert_manual_resolution_complete(
        requested_decisions=[original],
        resolved_decisions=[
            (
                original,
                SimpleNamespace(
                    page_number=2,
                    precise_boxes=[object()],
                ),
            ),
        ],
        **context(),
    )


def page_decision(number):
    return SimpleNamespace(
        kind="page",
        pageNumber=number,
        action="exempt",
        source="manual",
    )


def test_valid_page_decisions_are_accepted():
    assert_page_decisions_valid(
        request_decisions=[
            page_decision(1),
            page_decision(3),
        ],
        total_pages=3,
        **context(),
    )


@pytest.mark.parametrize(
    "number,total_pages",
    [
        (0, 3),
        (4, 3),
        (1, 0),
        (1, None),
    ],
)
def test_out_of_range_page_decision_is_rejected(
    number,
    total_pages,
):
    with pytest.raises(
        RedactionIntegrityError,
        match="PAGE_DECISION_OUT_OF_RANGE",
    ):
        assert_page_decisions_valid(
            request_decisions=[page_decision(number)],
            total_pages=total_pages,
            **context(),
        )


def test_duplicate_page_decisions_are_rejected():
    with pytest.raises(
        RedactionIntegrityError,
        match="DUPLICATE_PAGE_DECISION",
    ):
        assert_page_decisions_valid(
            request_decisions=[
                page_decision(2),
                page_decision(2),
            ],
            total_pages=5,
            **context(),
        )
