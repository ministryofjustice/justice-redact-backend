from pathlib import Path
from fastapi import HTTPException

from app.models.redaction_models import (
    ApplyRedactionsRequest,
    ImageRedactionDecision,
    PageDecision,
    TableRedactionDecision,
    TextRedactionDecision,
)
from app.services.document_store import get_document_or_404
from app.services.redaction_decision_store import upsert_redaction_decisions
from app.services.s3_keys import (
    exempt_pdf_key,
    original_pdf_key,
    redacted_pdf_key,
    vetted_pdf_key,
)
from app.services.s3_service import download_file_from_s3, upload_file_to_s3
from justice_redact.pdf_handler import extract_document
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


def build_pdf_handler_decisions(document_model, decisions):
    typed_decisions = []

    for decision in decisions:
        if isinstance(decision, TextRedactionDecision):
            typed_decisions.append(
                TextSpanDecision(
                    document_id=document_model.document_id,
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
                    document_id=document_model.document_id,
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
                    document_id=document_model.document_id,
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


def apply_redactions_for_document(
    document_id: str,
    request: ApplyRedactionsRequest,
) -> dict:
    upsert_redaction_decisions(
        document_id=document_id,
        decisions_json=request.model_dump(),
    )

    original_filename = get_document_or_404(document_id)["filename"]

    pdf_path = Path("/tmp") / f"{document_id}.pdf"
    redacted_output_path = Path("/tmp") / f"{document_id}-redacted.pdf"
    vetted_output_path = Path("/tmp") / f"{document_id}-vetted.pdf"
    exempt_output_path = Path("/tmp") / f"{document_id}-exempt.pdf"

    download_file_from_s3(
        original_pdf_key(document_id, original_filename),
        pdf_path,
    )

    document_model = extract_document(pdf_path)

    typed_decisions = build_pdf_handler_decisions(
        document_model=document_model,
        decisions=request.decisions,
    )

    page_decisions = build_page_decisions(request.decisions)
    exempt_page_numbers = page_decisions["exempt_page_numbers"]
    deleted_page_numbers = page_decisions["deleted_page_numbers"]
    redacted_excluded_page_numbers = sorted(
        set(exempt_page_numbers + deleted_page_numbers)
    )
    vetted_excluded_page_numbers = exempt_page_numbers

    if not typed_decisions and not exempt_page_numbers and not deleted_page_numbers:
        raise HTTPException(
            status_code=400,
            detail="No valid redaction or page decisions could be built",
        )

    apply_pdf_decisions(
        document=document_model,
        pdf_path=pdf_path,
        decisions=typed_decisions,
        output_path=redacted_output_path,
        excluded_page_numbers=redacted_excluded_page_numbers,
    )

    apply_vetted_pdf_highlights(
        document=document_model,
        pdf_path=pdf_path,
        decisions=typed_decisions,
        output_path=vetted_output_path,
        excluded_page_numbers=vetted_excluded_page_numbers,
    )

    if exempt_page_numbers:
        create_exempt_pdf(
            pdf_path=pdf_path,
            output_path=exempt_output_path,
            exempt_page_numbers=exempt_page_numbers,
        )

    upload_file_to_s3(
        redacted_output_path,
        redacted_pdf_key(document_id),
    )

    upload_file_to_s3(
        vetted_output_path,
        vetted_pdf_key(document_id),
    )

    if exempt_page_numbers:
        upload_file_to_s3(
            exempt_output_path,
            exempt_pdf_key(document_id),
        )

    return {
        "totalDecisionsApplied": len(typed_decisions),
        "exemptPages": exempt_page_numbers,
        "deletedPages": deleted_page_numbers,
        "redactedExcludedPages": redacted_excluded_page_numbers,
        "vettedExcludedPages": vetted_excluded_page_numbers,
        "decisionTypes": sorted({decision.kind for decision in request.decisions}),
        "exportPath": redacted_pdf_key(document_id),
        "vettedExportPath": vetted_pdf_key(document_id),
        "exemptExportPath": (
            exempt_pdf_key(document_id) if exempt_page_numbers else None
        ),
    }
