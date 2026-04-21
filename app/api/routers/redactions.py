from fastapi import APIRouter, HTTPException

from app.models.redaction_models import ApplyRedactionsRequest
from app.services.document_store import get_document_or_404
from app.services.redaction_service import apply_redactions_for_document

router = APIRouter(prefix="/documents", tags=["redactions"])


@router.post("/{document_id}/apply-redactions")
async def apply_redactions(document_id: str, request: ApplyRedactionsRequest):
    document = get_document_or_404(document_id)

    if document_id != request.documentId:
        raise HTTPException(status_code=400, detail="Document ID mismatch")

    if not request.decisions:
        raise HTTPException(status_code=400, detail="No redaction decisions supplied")

    try:
        summary = apply_redactions_for_document(
            document_id=document_id, request=request
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    document["status"] = "redaction_complete"
    document["exportPath"] = summary["exportPath"]
    document["redactionSummary"] = {
        "totalDecisionsApplied": summary["totalDecisionsApplied"],
        "decisionTypes": summary["decisionTypes"],
    }

    return {
        "documentId": document_id,
        "status": "redaction_complete",
        "exportPath": summary["exportPath"],
        "summary": document["redactionSummary"],
    }
