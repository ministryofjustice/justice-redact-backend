import asyncio

from fastapi import APIRouter, HTTPException

from app.models.redaction_models import ApplyRedactionsRequest
from app.services.document_store import get_document_or_404
from app.services.redaction_service import apply_redactions_for_document

router = APIRouter(prefix="/documents", tags=["redactions"])


async def apply_redactions_pipeline(
    document_id: str,
    request: ApplyRedactionsRequest,
) -> None:
    document = get_document_or_404(document_id)

    try:
        summary = apply_redactions_for_document(
            document_id=document_id,
            request=request,
        )

        document["status"] = "redaction_complete"
        document["exportPath"] = summary["exportPath"]
        document["redactionSummary"] = {
            "totalDecisionsApplied": summary["totalDecisionsApplied"],
            "decisionTypes": summary["decisionTypes"],
        }

    except Exception as exc:
        document["status"] = "redaction_failed"
        document["error"] = str(exc)


@router.post("/{document_id}/apply-redactions")
async def apply_redactions(document_id: str, request: ApplyRedactionsRequest):
    document = get_document_or_404(document_id)

    if document_id != request.documentId:
        raise HTTPException(status_code=400, detail="Document ID mismatch")

    if not request.decisions:
        raise HTTPException(status_code=400, detail="No redaction decisions supplied")

    document["status"] = "applying_redactions"
    document.pop("error", None)

    asyncio.create_task(
        apply_redactions_pipeline(
            document_id=document_id,
            request=request,
        )
    )

    return {
        "documentId": document_id,
        "status": "applying_redactions",
    }
