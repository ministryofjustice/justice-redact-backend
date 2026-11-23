"""Fail-closed coverage of all vetter-applied content decisions.

Never log SAR text, extracted content, image bytes, or complete
redaction payloads.
"""

from collections import Counter

from app.logging_config import logger


class RedactionIntegrityError(RuntimeError):
    """An intended redaction cannot be proven resolved."""


def _value(decision, *names):
    for name in names:
        value = getattr(decision, name, None)
        if value is not None:
            return value
    return None


def _kind(decision):
    kind = getattr(decision, "kind", None)

    if kind is not None:
        return kind

    name = type(decision).__name__

    if name == "TextSpanDecision":
        return "text"

    if name == "TableTextSpanDecision":
        return "table_cell"

    if name == "ImageRegionDecision":
        return (
            "image_area"
            if getattr(decision, "rect", None) is not None
            else "image"
        )

    return "unknown"


def _signature(decision):
    rect = getattr(decision, "rect", None)

    area = (
        tuple(
            getattr(rect, key, None)
            for key in ("x0", "y0", "x1", "y1")
        )
        if rect is not None
        else None
    )

    return (
        _kind(decision),
        _value(decision, "page_number", "pageNumber"),
        _value(decision, "item_id", "itemId"),
        _value(decision, "table_id", "tableId"),
        _value(decision, "cell_id", "cellId"),
        _value(decision, "image_id", "imageId"),
        getattr(decision, "start", None),
        getattr(decision, "end", None),
        _value(decision, "area_id", "areaId"),
        area,
        _value(
            decision,
            "redaction_group_id",
            "redactionGroupId",
        ),
        getattr(decision, "text", None),
        getattr(decision, "source", None),
        getattr(decision, "action", None),
    )


def _fail(
    code,
    stage,
    decision,
    index,
    *,
    document_id,
    run_id,
    claim_id,
    **details,
):
    page = _value(
        decision,
        "page_number",
        "pageNumber",
    )

    target = _value(
        decision,
        "image_id",
        "imageId",
        "cell_id",
        "cellId",
        "item_id",
        "itemId",
        "table_id",
        "tableId",
    )

    if target is not None:
        target = (
            str(target)
            .replace("\n", " ")
            .replace("\r", " ")[:128]
        )

    logger.error(
        "redaction_integrity_failed",
        extra={
            "event": "redaction_integrity_failed",
            "document_id": document_id,
            "run_id": run_id,
            "claim_id": claim_id,
            "stage": stage,
            "error_code": code,
            "decision_index": index,
            "decision_type": _kind(decision),
            "page_number": page,
            "target_id": target,
            "area_id": _value(
                decision,
                "area_id",
                "areaId",
            ),
            **details,
        },
    )

    raise RedactionIntegrityError(
        f"{code}: "
        f"stage={stage}, "
        f"index={index}, "
        f"type={_kind(decision)}, "
        f"page={page}, "
        f"target_id={target}"
    )


def assert_manual_conversion_complete(
    *,
    request_decisions,
    converted_decisions,
    document_id,
    run_id,
    claim_id,
):
    """Fail if any manual decision disappears during conversion."""

    requested = [
        (index, decision)
        for index, decision in enumerate(request_decisions)
        if _kind(decision) != "page"
    ]

    converted = Counter(
        _signature(decision)
        for decision in converted_decisions
    )

    for index, decision in requested:
        signature = _signature(decision)

        if converted[signature] <= 0:
            _fail(
                "MANUAL_DECISION_NOT_CONVERTED",
                "conversion",
                decision,
                index,
                document_id=document_id,
                run_id=run_id,
                claim_id=claim_id,
            )

        converted[signature] -= 1

    for index, decision in enumerate(converted_decisions):
        signature = _signature(decision)

        if converted[signature] > 0:
            _fail(
                "UNEXPECTED_CONVERTED_DECISION",
                "conversion",
                decision,
                index,
                document_id=document_id,
                run_id=run_id,
                claim_id=claim_id,
            )


def assert_manual_chunk_coverage(
    *,
    requested_decisions,
    decisions_by_chunk,
    document_id,
    run_id,
    claim_id,
):
    """Every manual redaction must belong to exactly one chunk."""

    assignments = Counter(
        id(decision)
        for chunk_decisions in decisions_by_chunk.values()
        for decision in chunk_decisions
    )

    for index, decision in enumerate(requested_decisions):
        count = assignments[id(decision)]

        if count != 1:
            code = (
                "MANUAL_DECISION_WITHOUT_GEOMETRY_CHUNK"
                if count == 0
                else "MANUAL_DECISION_IN_MULTIPLE_CHUNKS"
            )

            _fail(
                code,
                "chunk_assignment",
                decision,
                index,
                document_id=document_id,
                run_id=run_id,
                claim_id=claim_id,
                assigned_chunk_count=count,
            )


def assert_manual_resolution_complete(
    *,
    requested_decisions,
    resolved_decisions,
    document_id,
    run_id,
    claim_id,
):
    """Verify every manual decision across the entire document."""

    expected = {
        id(decision): (index, decision)
        for index, decision in enumerate(requested_decisions)
    }

    if len(expected) != len(requested_decisions):
        raise RedactionIntegrityError(
            "Repeated manual decision object in conversion"
        )

    seen = set()

    for decision, resolved in resolved_decisions:
        identity = id(decision)

        if identity not in expected:
            _fail(
                "UNEXPECTED_RESOLVED_MANUAL_DECISION",
                "resolution",
                decision,
                None,
                document_id=document_id,
                run_id=run_id,
                claim_id=claim_id,
            )

        index, _ = expected[identity]

        if identity in seen:
            _fail(
                "DUPLICATE_MANUAL_DECISION_RESOLUTION",
                "resolution",
                decision,
                index,
                document_id=document_id,
                run_id=run_id,
                claim_id=claim_id,
            )

        seen.add(identity)

        if resolved is None:
            _fail(
                "EMPTY_MANUAL_DECISION_RESOLUTION",
                "resolution",
                decision,
                index,
                document_id=document_id,
                run_id=run_id,
                claim_id=claim_id,
            )

        resolved_page = getattr(
            resolved,
            "page_number",
            None,
        )

        if resolved_page != decision.page_number:
            _fail(
                "MANUAL_RESOLUTION_PAGE_MISMATCH",
                "resolution",
                decision,
                index,
                document_id=document_id,
                run_id=run_id,
                claim_id=claim_id,
                resolved_page_number=resolved_page,
            )

        # Use exactly the supported geometry fields consumed by
        # the PDF export library, in the same priority order.
        # A merged_bbox alone is insufficient because the export
        # functions do not consume it as redaction geometry.
        boxes = next(
            (
                value
                for field in (
                    "precise_boxes",
                    "boxes",
                    "line_boxes",
                )
                if (value := getattr(resolved, field, None))
            ),
            None,
        )

        if not boxes:
            _fail(
                "MANUAL_RESOLUTION_HAS_NO_BOXES",
                "resolution",
                decision,
                index,
                document_id=document_id,
                run_id=run_id,
                claim_id=claim_id,
            )

    for identity, (index, decision) in expected.items():
        if identity not in seen:
            _fail(
                "UNRESOLVED_MANUAL_DECISION",
                "resolution",
                decision,
                index,
                document_id=document_id,
                run_id=run_id,
                claim_id=claim_id,
            )


def assert_page_decisions_valid(
    *,
    request_decisions,
    total_pages,
    document_id,
    run_id,
    claim_id,
):
    """Reject missing, out-of-range or conflicting page decisions."""

    page_decisions = [
        (index, decision)
        for index, decision in enumerate(request_decisions)
        if _kind(decision) == "page"
    ]

    if not page_decisions:
        return

    seen_pages = {}

    for index, decision in page_decisions:
        page_number = _value(
            decision,
            "pageNumber",
            "page_number",
        )

        if (
            not isinstance(total_pages, int)
            or isinstance(total_pages, bool)
            or total_pages < 1
            or not isinstance(page_number, int)
            or isinstance(page_number, bool)
            or not 1 <= page_number <= total_pages
        ):
            _fail(
                "PAGE_DECISION_OUT_OF_RANGE",
                "page_validation",
                decision,
                index,
                document_id=document_id,
                run_id=run_id,
                claim_id=claim_id,
            )

        if page_number in seen_pages:
            _fail(
                "DUPLICATE_PAGE_DECISION",
                "page_validation",
                decision,
                index,
                document_id=document_id,
                run_id=run_id,
                claim_id=claim_id,
                first_decision_index=seen_pages[page_number],
            )

        seen_pages[page_number] = index
