from pathlib import Path
import time
from fastapi import HTTPException

from justice_redact.pdf_handler.models import Document
from app.models.redaction_models import (
    ApplyRedactionsRequest,
    ImageRedactionDecision,
    PageDecision,
    TableRedactionDecision,
    TextRedactionDecision,
)
from app.services.document_store import get_document_or_404
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
from justice_redact.pdf_handler.resolution.resolve_any import resolve_pdf_decisions_once


class RedactionProcessingCancelled(Exception):
    pass


def assert_redaction_processing_active(
    is_redaction_active,
) -> None:
    if not is_redaction_active():
        raise RedactionProcessingCancelled(
            "Redaction processing is no longer authoritative"
        )


def build_pdf_handler_decisions(document_id: str, decisions):
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


def get_chunk_for_page(manifest: dict, page_number: int) -> dict | None:
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
) -> dict:
    pipeline_start = time.perf_counter()
    assert_redaction_processing_active(is_redaction_active)

    start = time.perf_counter()
    original_filename = get_document_or_404(document_id)["filename"]
    print(
        f"[REDACTION_TIMING] get_document={time.perf_counter() - start:.2f}s",
        flush=True,
    )

    pdf_path = Path("/tmp") / f"{document_id}-{run_id}.pdf"
    redacted_output_path = Path("/tmp") / f"{document_id}-{run_id}-redacted.pdf"
    vetted_output_path = Path("/tmp") / f"{document_id}-{run_id}-vetted.pdf"
    exempt_output_path = Path("/tmp") / f"{document_id}-{run_id}-exempt.pdf"

    start = time.perf_counter()
    download_file_from_s3(
        original_pdf_key(document_id, original_filename),
        pdf_path,
    )
    print(
        f"[REDACTION_TIMING] download_file_from_s3={time.perf_counter() - start:.2f}s",
        flush=True,
    )

    start = time.perf_counter()

    manifest = download_json_from_s3(
        document_geometry_manifest_key(document_id),
    )

    print(
        f"[REDACTION_TIMING] load_document_geometry_manifest={time.perf_counter() - start:.2f}s "
        f"chunks={len(manifest.get('chunks', []))} total_pages={manifest.get('totalPages')}",
        flush=True,
    )

    start = time.perf_counter()
    typed_decisions = build_pdf_handler_decisions(
        document_id=document_id,
        decisions=request.decisions,
    )
    print(
        f"[REDACTION_TIMING] build_pdf_handler_decisions={time.perf_counter() - start:.2f}s",
        flush=True,
    )

    start = time.perf_counter()

    decisions_by_chunk = group_decisions_by_chunk(
        manifest=manifest,
        typed_decisions=typed_decisions,
    )

    resolved_decisions = []

    for chunk_index, chunk_decisions in sorted(decisions_by_chunk.items()):
        assert_redaction_processing_active(is_redaction_active)
        chunk_start = time.perf_counter()

        chunk_geometry = download_json_from_s3(
            document_geometry_chunk_key(document_id, chunk_index),
        )

        chunk_document = Document.model_validate(chunk_geometry)
        chunk_document.source_path = str(pdf_path)

        chunk_resolved_decisions = resolve_pdf_decisions_once(
            document=chunk_document,
            decisions=chunk_decisions,
        )
        assert_redaction_processing_active(is_redaction_active)

        resolved_decisions.extend(chunk_resolved_decisions)

        print(
            f"[REDACTION_TIMING] resolve_pdf_decisions_chunk "
            f"chunk={chunk_index} "
            f"decisions={len(chunk_decisions)} "
            f"resolved={len(chunk_resolved_decisions)} "
            f"time={time.perf_counter() - chunk_start:.2f}s",
            flush=True,
        )

        del chunk_geometry
        del chunk_document
        del chunk_resolved_decisions

    unresolved_count = len(typed_decisions) - len(resolved_decisions)

    if unresolved_count:
        print(
            f"[REDACTION_TIMING] unresolved_decisions={unresolved_count}",
            flush=True,
        )

    print(
        f"[REDACTION_TIMING] resolve_pdf_decisions_once={time.perf_counter() - start:.2f}s "
        f"typed_decisions={len(typed_decisions)} "
        f"resolved={len(resolved_decisions)} "
        f"chunks_loaded={len(decisions_by_chunk)}",
        flush=True,
    )

    start = time.perf_counter()
    page_decisions = build_page_decisions(request.decisions)
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
    vetted_excluded_page_numbers = exempt_page_numbers
    print(
        f"[REDACTION_TIMING] build_page_decisions={time.perf_counter() - start:.2f}s",
        flush=True,
    )

    if not typed_decisions and not exempt_page_numbers and not deleted_page_numbers:
        raise HTTPException(
            status_code=400,
            detail="No valid redaction or page decisions could be built",
        )

    start = time.perf_counter()
    assert_redaction_processing_active(is_redaction_active)
    apply_pdf_decisions(
        document=None,
        pdf_path=pdf_path,
        resolved_decisions=resolved_decisions,
        output_path=redacted_output_path,
        excluded_page_numbers=redacted_excluded_page_numbers,
    )
    assert_redaction_processing_active(is_redaction_active)
    print(
        f"[REDACTION_TIMING] apply_pdf_decisions={time.perf_counter() - start:.2f}s",
        flush=True,
    )

    start = time.perf_counter()
    assert_redaction_processing_active(is_redaction_active)
    apply_vetted_pdf_highlights(
        document=None,
        pdf_path=pdf_path,
        resolved_decisions=resolved_decisions,
        output_path=vetted_output_path,
        excluded_page_numbers=vetted_excluded_page_numbers,
    )
    assert_redaction_processing_active(is_redaction_active)
    print(
        f"[REDACTION_TIMING] apply_vetted_pdf_highlights={time.perf_counter() - start:.2f}s",
        flush=True,
    )

    if exempt_page_numbers:
        start = time.perf_counter()
        assert_redaction_processing_active(is_redaction_active)
        create_exempt_pdf(
            pdf_path=pdf_path,
            output_path=exempt_output_path,
            exempt_page_numbers=exempt_page_numbers,
        )
        assert_redaction_processing_active(is_redaction_active)
        print(
            f"[REDACTION_TIMING] create_exempt_pdf={time.perf_counter() - start:.2f}s",
            flush=True,
        )

    start = time.perf_counter()
    assert_redaction_processing_active(is_redaction_active)
    upload_file_to_s3(
        redacted_output_path,
        redaction_run_redacted_pdf_key(
            document_id,
            run_id,
        ),
    )
    print(
        f"[REDACTION_TIMING] upload_redacted_pdf={time.perf_counter() - start:.2f}s",
        flush=True,
    )

    start = time.perf_counter()
    assert_redaction_processing_active(is_redaction_active)
    upload_file_to_s3(
        vetted_output_path,
        redaction_run_vetted_pdf_key(
            document_id,
            run_id,
        ),
    )
    print(
        f"[REDACTION_TIMING] upload_vetted_pdf={time.perf_counter() - start:.2f}s",
        flush=True,
    )

    if exempt_page_numbers:
        start = time.perf_counter()
        assert_redaction_processing_active(is_redaction_active)
        upload_file_to_s3(
            exempt_output_path,
            redaction_run_exempt_pdf_key(
                document_id,
                run_id,
            ),
        )
        print(
            f"[REDACTION_TIMING] upload_exempt_pdf={time.perf_counter() - start:.2f}s",
            flush=True,
        )

    print(
        f"[REDACTION_TIMING] apply_redactions_for_document_TOTAL={time.perf_counter() - pipeline_start:.2f}s",
        flush=True,
    )

    assert_redaction_processing_active(is_redaction_active)
    return {
        "totalDecisionsApplied": len(typed_decisions),
        "exemptPages": exempt_page_numbers,
        "deletedPages": deleted_page_numbers,
        "redactedExcludedPages": redacted_excluded_page_numbers,
        "vettedExcludedPages": vetted_excluded_page_numbers,
        "pageCounts": page_counts,
        "decisionTypes": sorted({decision.kind for decision in request.decisions}),
        "exportPath": redaction_run_redacted_pdf_key(
            document_id,
            run_id,
        ),
        "vettedExportPath": redaction_run_vetted_pdf_key(
            document_id,
            run_id,
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
