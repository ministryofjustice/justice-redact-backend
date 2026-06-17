import asyncio
import traceback

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException

from app.models.redaction_models import ApplyRedactionsRequest
from app.services.document_store import get_document_or_404, update_document_record
from app.services.redaction_service import apply_redactions_for_document

router = APIRouter(prefix="/documents", tags=["redactions"])


async def apply_redactions_pipeline(
    document_id: str,
    request: ApplyRedactionsRequest,
) -> None:

    try:
        apply_redactions_for_document(
            document_id=document_id,
            request=request,
        )

        update_document_record(
            document_id,
            status="redaction_complete",
            redaction_completed_at=datetime.now(timezone.utc),
        )

    except Exception as exc:
        traceback.print_exc()

        update_document_record(
            document_id,
            status="redaction_failed",
            redaction_completed_at=datetime.now(timezone.utc),
            error_message=str(exc),
        )


@router.post("/{document_id}/apply-redactions")
async def apply_redactions(document_id: str, request: ApplyRedactionsRequest):
    document = get_document_or_404(document_id)

    if document_id != request.documentId:
        raise HTTPException(status_code=400, detail="Document ID mismatch")

    if not request.decisions:
        raise HTTPException(status_code=400, detail="No redaction decisions supplied")

    update_document_record(
        document_id,
        status="applying_redactions",
        redaction_started_at=datetime.now(timezone.utc),
        redaction_completed_at=None,
        clear_error=True,
    )

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
