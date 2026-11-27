from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.redaction_models import (
    ApplyRedactionsRequest,
    SaveRedactionDecisionsRequest,
    ImageAreaRedactionDecision,
    ImageRedactionDecision,
)
from app.services import redaction_service
from app.services.redaction_integrity import (
    RedactionIntegrityError,
    assert_manual_conversion_complete,
    assert_manual_resolution_complete,
)


AREA = {
    "kind": "image_area",
    "pageNumber": 12,
    "imageId": "page-12_img_0001",
    "areaId": "area-1",
    "rect": {
        "x0": 0.15,
        "y0": 0.2,
        "x1": 0.6,
        "y1": 0.45,
    },
    "action": "redact",
    "source": "manual",
}


def make_area(**overrides):
    payload = {
        **AREA,
        "rect": dict(AREA["rect"]),
        **overrides,
    }
    return ImageAreaRedactionDecision.model_validate(payload)


def test_area_decision_parses_in_save_request():
    request = SaveRedactionDecisionsRequest(
        documentId="document-1",
        decisions=[make_area()],
        expectedRevision=3,
    )

    assert isinstance(
        request.decisions[0],
        ImageAreaRedactionDecision,
    )

    serialized = request.model_dump(
        exclude_none=True
    )

    assert serialized["decisions"][0]["kind"] == "image_area"
    assert serialized["decisions"][0]["areaId"] == "area-1"
    assert serialized["decisions"][0]["rect"] == AREA["rect"]


def test_area_decision_parses_in_apply_request():
    request = ApplyRedactionsRequest.model_validate({
        "documentId": "document-1",
        "decisions": [AREA],
        "expectedRevision": 4,
    })

    assert isinstance(
        request.decisions[0],
        ImageAreaRedactionDecision,
    )


def test_area_decision_converts_without_losing_geometry():
    original = make_area()

    converted = redaction_service.build_pdf_handler_decisions(
        document_id="document-1",
        decisions=[original],
    )

    assert len(converted) == 1

    decision = converted[0]

    assert decision.image_id == original.imageId
    assert decision.page_number == original.pageNumber
    assert decision.area_id == original.areaId
    assert decision.rect.model_dump() == AREA["rect"]

    assert_manual_conversion_complete(
        request_decisions=[original],
        converted_decisions=converted,
        document_id="document-1",
        run_id="run-1",
        claim_id="claim-1",
    )


def test_area_decision_is_covered_by_resolution_integrity():
    converted = redaction_service.build_pdf_handler_decisions(
        document_id="document-1",
        decisions=[make_area()],
    )

    with pytest.raises(
        RedactionIntegrityError,
        match="UNRESOLVED_MANUAL_DECISION",
    ):
        assert_manual_resolution_complete(
            requested_decisions=converted,
            resolved_decisions=[],
            document_id="document-1",
            run_id="run-1",
            claim_id="claim-1",
        )


def test_area_resolution_integrity_accepts_resolved_geometry():
    converted = redaction_service.build_pdf_handler_decisions(
        document_id="document-1",
        decisions=[make_area()],
    )
    decision = converted[0]

    assert_manual_resolution_complete(
        requested_decisions=converted,
        resolved_decisions=[
            (
                decision,
                SimpleNamespace(
                    page_number=12,
                    boxes=[object()],
                ),
            ),
        ],
        document_id="document-1",
        run_id="run-1",
        claim_id="claim-1",
    )


def test_whole_image_decision_remains_compatible():
    original = ImageRedactionDecision(
        kind="image",
        pageNumber=12,
        imageId="page-12_img_0001",
        action="redact",
        source="manual",
    )

    converted = redaction_service.build_pdf_handler_decisions(
        document_id="document-1",
        decisions=[original],
    )

    assert len(converted) == 1
    assert converted[0].rect is None
    assert converted[0].area_id is None


def test_outdated_python_package_fails_closed(monkeypatch):
    monkeypatch.setattr(
        redaction_service,
        "ImageRegionDecision",
        SimpleNamespace(model_fields={}),
    )

    with pytest.raises(
        RedactionIntegrityError,
        match="IMAGE_AREA_PDF_HANDLER_UNSUPPORTED",
    ):
        redaction_service.build_pdf_handler_decisions(
            document_id="document-1",
            decisions=[make_area()],
        )


@pytest.mark.parametrize(
    "rect",
    [
        {"x0": -0.1, "y0": 0, "x1": 0.5, "y1": 0.5},
        {"x0": 0, "y0": 0, "x1": 1.1, "y1": 0.5},
        {"x0": 0.5, "y0": 0, "x1": 0.5, "y1": 0.5},
        {"x0": 0.8, "y0": 0, "x1": 0.2, "y1": 0.5},
        {"x0": 0, "y0": 0.5, "x1": 0.5, "y1": 0.5},
        {"x0": float("nan"), "y0": 0, "x1": 0.5, "y1": 0.5},
        {"x0": 0, "y0": 0, "x1": float("inf"), "y1": 0.5},
    ],
)
def test_invalid_area_geometry_is_rejected(rect):
    with pytest.raises(ValidationError):
        make_area(rect=rect)


@pytest.mark.parametrize(
    "changes",
    [
        {"pageNumber": 0},
        {"imageId": ""},
        {"imageId": "  "},
        {"areaId": ""},
        {"areaId": "  "},
        {"kind": "unexpected"},
    ],
)
def test_invalid_area_decision_is_rejected(changes):
    with pytest.raises(ValidationError):
        make_area(**changes)


def test_missing_rectangle_is_rejected():
    payload = dict(AREA)
    del payload["rect"]

    with pytest.raises(ValidationError):
        ImageAreaRedactionDecision.model_validate(payload)


def test_unknown_rectangle_fields_are_rejected():
    rect = {
        **AREA["rect"],
        "unexpected": True,
    }

    with pytest.raises(ValidationError):
        make_area(rect=rect)


def test_multiple_areas_remain_separate_decisions():
    first = make_area(areaId="area-1")
    second = make_area(
        areaId="area-2",
        rect={
            "x0": 0.3,
            "y0": 0.3,
            "x1": 0.8,
            "y1": 0.8,
        },
    )

    converted = redaction_service.build_pdf_handler_decisions(
        document_id="document-1",
        decisions=[first, second],
    )

    assert len(converted) == 2
    assert converted[0].area_id == "area-1"
    assert converted[1].area_id == "area-2"
    assert converted[0].rect != converted[1].rect
