from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
import time

from fastapi import HTTPException

from justice_redact.pdf_handler.models import Document
from justice_redact.pdf_handler.apply import (
    apply_pdf_decisions,
    apply_vetted_pdf_highlights,
    create_exempt_pdf,
)
from justice_redact.pdf_handler.decisions import (
    ImageRegionDecision,
    TableTextSpanDecision,
    TextSpanDecision,
)
from justice_redact.pdf_handler.resolution.resolve_any import (
    resolve_pdf_decisions_once,
)

from app.models.redaction_models import (
    ApplyRedactionsRequest,
    ImageRedactionDecision,
    PageDecision,
    TableRedactionDecision,
    TextRedactionDecision,
)
from app.services.document_store import get_document_or_404
from app.services.review_result_store import get_review_result
from app.services.s3_keys import (
    document_geometry_chunk_key,
    document_geometry_manifest_key,
    original_pdf_key,
    redaction_run_exempt_pdf_key,
    redaction_run_redacted_pdf_key,
    redaction_run_vetted_pdf_key,
)
from app.services.s3_service import (
    download_file_from_s3,
    download_json_from_s3,
    upload_file_to_s3,
)


class RedactionProcessingCancelled(Exception):
    pass


REDACTION_PROGRESS_STARTED = 1
REDACTION_PROGRESS_SETUP_COMPLETE = 5
REDACTION_PROGRESS_RESOLUTION_COMPLETE = 25
REDACTION_PROGRESS_REDACTED_PAGE_WORK_COMPLETE = 54
REDACTION_PROGRESS_REDACTED_COMPLETE = 55
REDACTION_PROGRESS_VETTED_PAGE_WORK_COMPLETE = 79
REDACTION_PROGRESS_VETTED_COMPLETE = 80
REDACTION_PROGRESS_EXEMPT_PAGE_WORK_COMPLETE = 89
REDACTION_PROGRESS_EXEMPT_COMPLETE = 90
REDACTION_PROGRESS_UPLOADS_COMPLETE = 98
REDACTION_PROGRESS_READY_TO_COMPLETE = 99


def calculate_redaction_stage_progress(
    *,
    start_progress: int,
    end_progress: int,
    completed: int,
    total: int,
) -> int:
    if start_progress < 0 or end_progress > 99 or end_progress < start_progress:
        raise ValueError("Invalid redaction progress range")

    if total <= 0:
        raise ValueError("Progress total must be greater than 0")

    if completed < 0 or completed > total:
        raise ValueError("Progress completed must be between 0 and total")

    progress_span = end_progress - start_progress

    progress = start_progress + int(progress_span * Fraction(completed, total))

    return min(
        progress,
        end_progress,
    )


def assert_redaction_processing_active(
    is_redaction_active,
) -> None:
    if not is_redaction_active():
        raise RedactionProcessingCancelled(
            "Redaction processing is no longer authoritative"
        )


def build_pdf_handler_decisions(
    document_id: str,
    decisions,
):
    """
    Convert saved vetter decisions into justice-redact PDF decisions.
    """

    typed_decisions = []

    for decision in decisions:
        if isinstance(decision, TextRedactionDecision):
            typed_decisions.append(
                TextSpanDecision(
                    document_id=document_id,
                    page_number=decision.pageNumber,
                    item_id=decision.itemId,
                    start=decision.start,
                    end=decision.end,
                    text=decision.text,
                    source=decision.source,
                    action=decision.action,
                )
            )
            continue

        if isinstance(decision, TableRedactionDecision):
            typed_decisions.append(
                TableTextSpanDecision(
                    document_id=document_id,
                    page_number=decision.pageNumber,
                    table_id=decision.tableId,
                    cell_id=decision.cellId,
                    start=decision.start,
                    end=decision.end,
                    text=decision.text,
                    source=decision.source,
                    action=decision.action,
                )
            )
            continue

        if isinstance(decision, ImageRedactionDecision):
            typed_decisions.append(
                ImageRegionDecision(
                    document_id=document_id,
                    page_number=decision.pageNumber,
                    image_id=decision.imageId,
                    source=decision.source,
                    action=decision.action,
                )
            )
            continue

    return typed_decisions


def build_ai_pdf_handler_decisions(
    document_id: str,
    findings: list[dict],
):
    """
    Convert persisted AI review findings into justice-redact PDF decisions.

    These decisions are used only to resolve the AI suggestions back to
    their PDF coordinates. They are not applied as redactions.
    """

    typed_decisions = []

    for finding in findings:
        kind = finding.get("kind")
        page_number = finding.get("pageNumber")

        if not isinstance(page_number, int) or page_number <= 0:
            continue

        if kind == "text":
            item_id = finding.get("itemId")
            start = finding.get("entityStart")
            end = finding.get("entityEnd")

            if (
                not isinstance(item_id, str)
                or not item_id
                or not isinstance(start, int)
                or not isinstance(end, int)
                or end <= start
            ):
                continue

            typed_decisions.append(
                TextSpanDecision(
                    document_id=document_id,
                    page_number=page_number,
                    item_id=item_id,
                    start=start,
                    end=end,
                    text=finding.get("entityText", ""),
                    source="ai",
                    action="suggest",
                )
            )
            continue

        if kind == "table_cell":
            table_id = finding.get("tableId")
            cell_id = finding.get("cellId")
            start = finding.get("entityStart")
            end = finding.get("entityEnd")

            if (
                not isinstance(table_id, str)
                or not table_id
                or not isinstance(cell_id, str)
                or not cell_id
                or not isinstance(start, int)
                or not isinstance(end, int)
                or end <= start
            ):
                continue

            typed_decisions.append(
                TableTextSpanDecision(
                    document_id=document_id,
                    page_number=page_number,
                    table_id=table_id,
                    cell_id=cell_id,
                    start=start,
                    end=end,
                    text=finding.get("entityText", ""),
                    source="ai",
                    action="suggest",
                )
            )
            continue

        if kind == "image":
            image_id = finding.get("imageId")

            if not isinstance(image_id, str) or not image_id:
                continue

            typed_decisions.append(
                ImageRegionDecision(
                    document_id=document_id,
                    page_number=page_number,
                    image_id=image_id,
                    source="ai",
                    action="suggest",
                )
            )

    return typed_decisions


def build_page_decisions(decisions):
    exempt_page_numbers = []
    deleted_page_numbers = []

    for decision in decisions:
        if not isinstance(decision, PageDecision):
            continue

        if decision.action == "exempt":
            exempt_page_numbers.append(decision.pageNumber)
            continue

        if decision.action == "delete":
            deleted_page_numbers.append(decision.pageNumber)
            continue

    return {
        "exempt_page_numbers": sorted(set(exempt_page_numbers)),
        "deleted_page_numbers": sorted(set(deleted_page_numbers)),
    }


def get_chunk_for_page(
    manifest: dict,
    page_number: int,
) -> dict | None:
    for chunk in manifest.get("chunks", []):
        if chunk["pageStart"] <= page_number <= chunk["pageEnd"]:
            return chunk

    return None


def group_decisions_by_chunk(
    manifest: dict,
    typed_decisions: list,
) -> dict[int, list]:
    grouped: dict[int, list] = {}

    for decision in typed_decisions:
        chunk = get_chunk_for_page(
            manifest=manifest,
            page_number=decision.page_number,
        )

        if chunk is None:
            continue

        chunk_index = chunk["chunkIndex"]
        grouped.setdefault(chunk_index, []).append(decision)

    return grouped


def apply_redactions_for_document(
    *,
    document_id: str,
    run_id: str,
    request: ApplyRedactionsRequest,
    is_redaction_active=lambda: True,
    progress_callback: Callable[[int], None] | None = None,
) -> dict:
    pipeline_start = time.perf_counter()

    def report_progress(
        progress: int,
    ) -> None:
        if progress_callback is not None:
            progress_callback(progress)

    def report_stage_progress(
        *,
        start_progress: int,
        end_progress: int,
        completed: int,
        total: int,
    ) -> None:
        if progress_callback is None:
            return

        progress_callback(
            calculate_redaction_stage_progress(
                start_progress=start_progress,
                end_progress=end_progress,
                completed=completed,
                total=total,
            )
        )

    assert_redaction_processing_active(
        is_redaction_active,
    )

    report_progress(
        REDACTION_PROGRESS_STARTED,
    )

    start = time.perf_counter()

    original_filename = get_document_or_404(
        document_id,
    )["filename"]

    print(
        f"[REDACTION_TIMING] " f"get_document={time.perf_counter() - start:.2f}s",
        flush=True,
    )

    # AI suggestions are persisted separately from the vetter's decisions
    # in the review result. They are exported as PDF highlight annotations,
    # but they are never applied as redactions.
    start = time.perf_counter()

    review_result = get_review_result(
        document_id,
    )

    ai_findings = (
        review_result.get("findings", []) if isinstance(review_result, dict) else []
    )

    if not isinstance(ai_findings, list):
        ai_findings = []

    ai_decisions = build_ai_pdf_handler_decisions(
        document_id=document_id,
        findings=ai_findings,
    )

    print(
        f"[REDACTION_TIMING] "
        f"build_ai_pdf_handler_decisions="
        f"{time.perf_counter() - start:.2f}s "
        f"findings={len(ai_findings)} "
        f"decisions={len(ai_decisions)}",
        flush=True,
    )

    pdf_path = Path("/tmp") / f"{document_id}-{run_id}.pdf"

    redacted_output_path = Path("/tmp") / f"{document_id}-{run_id}-redacted.pdf"

    vetted_output_path = Path("/tmp") / f"{document_id}-{run_id}-vetted.pdf"

    exempt_output_path = Path("/tmp") / f"{document_id}-{run_id}-exempt.pdf"

    start = time.perf_counter()

    download_file_from_s3(
        original_pdf_key(
            document_id,
            original_filename,
        ),
        pdf_path,
    )

    print(
        f"[REDACTION_TIMING] "
        f"download_file_from_s3="
        f"{time.perf_counter() - start:.2f}s",
        flush=True,
    )

    start = time.perf_counter()

    manifest = download_json_from_s3(
        document_geometry_manifest_key(
            document_id,
        ),
    )

    print(
        f"[REDACTION_TIMING] "
        f"load_document_geometry_manifest="
        f"{time.perf_counter() - start:.2f}s "
        f"chunks={len(manifest.get('chunks', []))} "
        f"total_pages={manifest.get('totalPages')}",
        flush=True,
    )

    start = time.perf_counter()

    typed_decisions = build_pdf_handler_decisions(
        document_id=document_id,
        decisions=request.decisions,
    )

    print(
        f"[REDACTION_TIMING] "
        f"build_pdf_handler_decisions="
        f"{time.perf_counter() - start:.2f}s "
        f"decisions={len(typed_decisions)}",
        flush=True,
    )

    # Resolve vetter decisions and AI suggestions in the same geometry pass.
    # This avoids downloading and parsing the same geometry chunks twice.
    all_pdf_decisions = [
        *typed_decisions,
        *ai_decisions,
    ]

    start = time.perf_counter()

    decisions_by_chunk = group_decisions_by_chunk(
        manifest=manifest,
        typed_decisions=all_pdf_decisions,
    )

    report_progress(
        REDACTION_PROGRESS_SETUP_COMPLETE,
    )

    sorted_decision_chunks = sorted(decisions_by_chunk.items())

    resolved_decisions = []
    resolved_ai_suggestions = []

    for completed_chunks, (
        chunk_index,
        chunk_decisions,
    ) in enumerate(
        sorted_decision_chunks,
        start=1,
    ):
        assert_redaction_processing_active(
            is_redaction_active,
        )

        chunk_start = time.perf_counter()

        chunk_geometry = download_json_from_s3(
            document_geometry_chunk_key(
                document_id,
                chunk_index,
            ),
        )

        chunk_document = Document.model_validate(
            chunk_geometry,
        )

        chunk_document.source_path = str(
            pdf_path,
        )

        chunk_resolved_decisions = resolve_pdf_decisions_once(
            document=chunk_document,
            decisions=chunk_decisions,
        )

        assert_redaction_processing_active(
            is_redaction_active,
        )

        for decision, resolved in chunk_resolved_decisions:
            if decision.source == "ai":
                resolved_ai_suggestions.append((decision, resolved))
            else:
                resolved_decisions.append((decision, resolved))

        print(
            f"[REDACTION_TIMING] "
            f"resolve_pdf_decisions_chunk "
            f"chunk={chunk_index} "
            f"decisions={len(chunk_decisions)} "
            f"resolved={len(chunk_resolved_decisions)} "
            f"time="
            f"{time.perf_counter() - chunk_start:.2f}s",
            flush=True,
        )

        del chunk_geometry
        del chunk_document
        del chunk_resolved_decisions

        report_stage_progress(
            start_progress=REDACTION_PROGRESS_SETUP_COMPLETE,
            end_progress=REDACTION_PROGRESS_RESOLUTION_COMPLETE,
            completed=completed_chunks,
            total=len(sorted_decision_chunks),
        )

    if not sorted_decision_chunks:
        report_progress(
            REDACTION_PROGRESS_RESOLUTION_COMPLETE,
        )

    unresolved_decision_count = len(typed_decisions) - len(resolved_decisions)

    unresolved_ai_count = len(ai_decisions) - len(resolved_ai_suggestions)

    if unresolved_decision_count:
        print(
            f"[REDACTION_TIMING] "
            f"unresolved_decisions="
            f"{unresolved_decision_count}",
            flush=True,
        )

    if unresolved_ai_count:
        print(
            f"[REDACTION_TIMING] "
            f"unresolved_ai_suggestions="
            f"{unresolved_ai_count}",
            flush=True,
        )

    print(
        f"[REDACTION_TIMING] "
        f"resolve_pdf_decisions_once="
        f"{time.perf_counter() - start:.2f}s "
        f"manual_decisions={len(typed_decisions)} "
        f"manual_resolved={len(resolved_decisions)} "
        f"ai_decisions={len(ai_decisions)} "
        f"ai_resolved={len(resolved_ai_suggestions)} "
        f"chunks_loaded={len(decisions_by_chunk)}",
        flush=True,
    )

    start = time.perf_counter()

    page_decisions = build_page_decisions(
        request.decisions,
    )

    exempt_page_numbers = page_decisions["exempt_page_numbers"]

    deleted_page_numbers = page_decisions["deleted_page_numbers"]

    original_page_count = manifest.get("totalPages") or 0

    valid_exempt_page_numbers = [
        page_number
        for page_number in exempt_page_numbers
        if 1 <= page_number <= original_page_count
    ]

    valid_deleted_page_numbers = [
        page_number
        for page_number in deleted_page_numbers
        if 1 <= page_number <= original_page_count
    ]

    page_counts = {
        "original": original_page_count,
        "exempt": len(valid_exempt_page_numbers),
        "deleted": len(valid_deleted_page_numbers),
        "redacted": max(
            original_page_count
            - len(valid_exempt_page_numbers)
            - len(valid_deleted_page_numbers),
            0,
        ),
    }

    redacted_excluded_page_numbers = sorted(
        set(exempt_page_numbers + deleted_page_numbers)
    )

    # Exempt pages are removed from the vetted copy because they are
    # exported separately. Deleted pages remain in the vetted copy.
    vetted_excluded_page_numbers = exempt_page_numbers

    print(
        f"[REDACTION_TIMING] "
        f"build_page_decisions="
        f"{time.perf_counter() - start:.2f}s",
        flush=True,
    )

    # AI suggestions alone must never make an Apply Redactions request
    # valid. Apply is driven by explicit vetter/page decisions.
    if not typed_decisions and not exempt_page_numbers and not deleted_page_numbers:
        raise HTTPException(
            status_code=400,
            detail=("No valid redaction or page " "decisions could be built"),
        )

    # REDACTED PDF
    #
    # Contains only the vetter's applied redactions.
    # AI suggestions are intentionally NOT included.

    start = time.perf_counter()

    assert_redaction_processing_active(
        is_redaction_active,
    )

    apply_pdf_decisions(
        document=None,
        pdf_path=pdf_path,
        resolved_decisions=resolved_decisions,
        output_path=redacted_output_path,
        excluded_page_numbers=(redacted_excluded_page_numbers),
        progress_callback=lambda completed, total: (
            report_stage_progress(
                start_progress=(REDACTION_PROGRESS_RESOLUTION_COMPLETE),
                end_progress=(REDACTION_PROGRESS_REDACTED_PAGE_WORK_COMPLETE),
                completed=completed,
                total=total,
            )
        ),
    )

    assert_redaction_processing_active(
        is_redaction_active,
    )

    report_progress(
        REDACTION_PROGRESS_REDACTED_COMPLETE,
    )

    print(
        f"[REDACTION_TIMING] "
        f"apply_pdf_decisions="
        f"{time.perf_counter() - start:.2f}s",
        flush=True,
    )

    # VETTED PDF
    #
    # Contains:
    # - AI suggestions as blue Highlight annotations.
    # - vetter decisions as orange unapplied Redact annotations.

    start = time.perf_counter()

    assert_redaction_processing_active(
        is_redaction_active,
    )

    apply_vetted_pdf_highlights(
        document=None,
        pdf_path=pdf_path,
        resolved_decisions=resolved_decisions,
        resolved_ai_suggestions=(resolved_ai_suggestions),
        output_path=vetted_output_path,
        excluded_page_numbers=(vetted_excluded_page_numbers),
        progress_callback=lambda completed, total: (
            report_stage_progress(
                start_progress=(REDACTION_PROGRESS_REDACTED_COMPLETE),
                end_progress=(REDACTION_PROGRESS_VETTED_PAGE_WORK_COMPLETE),
                completed=completed,
                total=total,
            )
        ),
    )

    assert_redaction_processing_active(
        is_redaction_active,
    )

    report_progress(
        REDACTION_PROGRESS_VETTED_COMPLETE,
    )

    print(
        f"[REDACTION_TIMING] "
        f"apply_vetted_pdf_highlights="
        f"{time.perf_counter() - start:.2f}s",
        flush=True,
    )

    # EXEMPT PDF
    #
    # Contains only pages marked exempt and shows the AI
    # suggestions applicable to those original pages.

    if exempt_page_numbers:
        start = time.perf_counter()

        assert_redaction_processing_active(
            is_redaction_active,
        )

        create_exempt_pdf(
            pdf_path=pdf_path,
            output_path=exempt_output_path,
            exempt_page_numbers=(exempt_page_numbers),
            resolved_ai_suggestions=(resolved_ai_suggestions),
            progress_callback=lambda completed, total: (
                report_stage_progress(
                    start_progress=(REDACTION_PROGRESS_VETTED_COMPLETE),
                    end_progress=(REDACTION_PROGRESS_EXEMPT_PAGE_WORK_COMPLETE),
                    completed=completed,
                    total=total,
                )
            ),
        )

        assert_redaction_processing_active(
            is_redaction_active,
        )

        report_progress(
            REDACTION_PROGRESS_EXEMPT_COMPLETE,
        )

        print(
            f"[REDACTION_TIMING] "
            f"create_exempt_pdf="
            f"{time.perf_counter() - start:.2f}s",
            flush=True,
        )

    else:
        report_progress(
            REDACTION_PROGRESS_EXEMPT_COMPLETE,
        )

    # UPLOAD EXPORTS

    upload_count = 3 if exempt_page_numbers else 2
    completed_uploads = 0

    start = time.perf_counter()

    assert_redaction_processing_active(
        is_redaction_active,
    )

    upload_file_to_s3(
        redacted_output_path,
        redaction_run_redacted_pdf_key(
            document_id,
            run_id,
        ),
    )

    completed_uploads += 1

    report_stage_progress(
        start_progress=REDACTION_PROGRESS_EXEMPT_COMPLETE,
        end_progress=REDACTION_PROGRESS_UPLOADS_COMPLETE,
        completed=completed_uploads,
        total=upload_count,
    )

    print(
        f"[REDACTION_TIMING] "
        f"upload_redacted_pdf="
        f"{time.perf_counter() - start:.2f}s",
        flush=True,
    )

    start = time.perf_counter()

    assert_redaction_processing_active(
        is_redaction_active,
    )

    upload_file_to_s3(
        vetted_output_path,
        redaction_run_vetted_pdf_key(
            document_id,
            run_id,
        ),
    )

    completed_uploads += 1

    report_stage_progress(
        start_progress=REDACTION_PROGRESS_EXEMPT_COMPLETE,
        end_progress=REDACTION_PROGRESS_UPLOADS_COMPLETE,
        completed=completed_uploads,
        total=upload_count,
    )

    print(
        f"[REDACTION_TIMING] "
        f"upload_vetted_pdf="
        f"{time.perf_counter() - start:.2f}s",
        flush=True,
    )

    if exempt_page_numbers:
        start = time.perf_counter()

        assert_redaction_processing_active(
            is_redaction_active,
        )

        upload_file_to_s3(
            exempt_output_path,
            redaction_run_exempt_pdf_key(
                document_id,
                run_id,
            ),
        )

        completed_uploads += 1

        report_stage_progress(
            start_progress=REDACTION_PROGRESS_EXEMPT_COMPLETE,
            end_progress=REDACTION_PROGRESS_UPLOADS_COMPLETE,
            completed=completed_uploads,
            total=upload_count,
        )

        print(
            f"[REDACTION_TIMING] "
            f"upload_exempt_pdf="
            f"{time.perf_counter() - start:.2f}s",
            flush=True,
        )

    print(
        f"[REDACTION_TIMING] "
        f"apply_redactions_for_document_TOTAL="
        f"{time.perf_counter() - pipeline_start:.2f}s",
        flush=True,
    )

    assert_redaction_processing_active(
        is_redaction_active,
    )

    report_progress(
        REDACTION_PROGRESS_READY_TO_COMPLETE,
    )

    return {
        "totalDecisionsApplied": len(typed_decisions),
        "exemptPages": exempt_page_numbers,
        "deletedPages": deleted_page_numbers,
        "redactedExcludedPages": (redacted_excluded_page_numbers),
        "vettedExcludedPages": (vetted_excluded_page_numbers),
        "pageCounts": page_counts,
        "decisionTypes": sorted({decision.kind for decision in request.decisions}),
        "exportPath": (
            redaction_run_redacted_pdf_key(
                document_id,
                run_id,
            )
        ),
        "vettedExportPath": (
            redaction_run_vetted_pdf_key(
                document_id,
                run_id,
            )
        ),
        "exemptExportPath": (
            redaction_run_exempt_pdf_key(
                document_id,
                run_id,
            )
            if exempt_page_numbers
            else None
        ),
    }
