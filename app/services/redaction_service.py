from fastapi import HTTPException
from justice_redact.pdf_handler import extract_document
from justice_redact.pdf_handler.apply import (
    apply_pdf_decisions,
    apply_vetted_pdf_highlights,
)
from justice_redact.pdf_handler.decisions import (
    ImageRegionDecision,
    TableTextSpanDecision,
    TextSpanDecision,
)

from app.models.redaction_models import (
    ApplyRedactionsRequest,
    ImageRedactionDecision,
    TableRedactionDecision,
    TextRedactionDecision,
)
from app.services.file_store import (
    decisions_path,
    export_pdf_path,
    vetted_pdf_path,
    upload_pdf_path,
    write_json,
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


def apply_redactions_for_document(
    document_id: str,
    request: ApplyRedactionsRequest,
) -> dict:
    write_json(decisions_path(document_id), request.model_dump())

    pdf_path = upload_pdf_path(document_id)

    redacted_output_path = export_pdf_path(document_id)
    vetted_output_path = vetted_pdf_path(document_id)

    document_model = extract_document(pdf_path)
    typed_decisions = build_pdf_handler_decisions(
        document_model=document_model,
        decisions=request.decisions,
    )

    if not typed_decisions:
        raise HTTPException(
            status_code=400,
            detail="No valid redaction decisions could be built",
        )

    apply_pdf_decisions(
        document=document_model,
        pdf_path=pdf_path,
        decisions=typed_decisions,
        output_path=redacted_output_path,
    )

    apply_vetted_pdf_highlights(
        document=document_model,
        pdf_path=pdf_path,
        decisions=typed_decisions,
        output_path=vetted_output_path,
    )

    return {
        "totalDecisionsApplied": len(typed_decisions),
        "decisionTypes": sorted({decision.kind for decision in request.decisions}),
        "exportPath": str(redacted_output_path),
        "vettedExportPath": str(vetted_output_path),
    }
