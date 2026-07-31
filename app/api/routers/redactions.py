import time

from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.logging_config import logger
from app.models.redaction_models import ApplyRedactionsRequest
from app.services.document_store import get_document_or_404, update_document_record
from app.services.redaction_service import apply_redactions_for_document
from app.services.redaction_decision_store import (
    get_redaction_decisions,
    upsert_redaction_decisions,
)

router = APIRouter(prefix="/documents", tags=["redactions"])


def apply_redactions_pipeline(
    document_id: str,
    request: ApplyRedactionsRequest,
) -> None:
    """
    Background task (kicked off via asyncio.create_task in the route below)
    that actually applies the redactions and updates the document's status.
    Runs after the HTTP response has already been returned to the client,
    so any success/failure here can only be observed via the document's
    status field or - now - via these log events.
    """
    start = time.time()

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

        logger.info(
            "redaction_completed",
            extra={
                "event": "redaction_completed",
                "document_id": document_id,
                "redaction_count": len(request.decisions),
                "duration_ms": round((time.time() - start) * 1000, 2),
            },
        )

    except Exception as exc:
        # logger.exception attaches the full traceback as structured data
        # (exc_info=True is set automatically), so it's searchable in
        # OpenSearch alongside the rest of the event - previously this was
        # traceback.print_exc(), which wrote plain text to stderr and was
        # invisible to the JSON-based logging/Fluent Bit pipeline entirely.
        logger.exception(
            "redaction_failed",
            extra={
                "event": "redaction_failed",
                "document_id": document_id,
                "error": str(exc),
                "duration_ms": round((time.time() - start) * 1000, 2),
            },
        )

        update_document_record(
            document_id,
            status="redaction_failed",
            redaction_completed_at=datetime.now(timezone.utc),
            error_message=str(exc),
        )


@router.get("/{document_id}/redaction-decisions")
async def get_document_redaction_decisions(document_id: str):
    get_document_or_404(document_id)

    decision_set = get_redaction_decisions(document_id)

    if decision_set is None:
        return {
            "documentId": document_id,
            "decisions": [],
        }

    return decision_set


@router.put("/{document_id}/redaction-decisions")
async def save_document_redaction_decisions(
    document_id: str,
    request: ApplyRedactionsRequest,
):
    get_document_or_404(document_id)

    if document_id != request.documentId:
        raise HTTPException(
            status_code=400,
            detail="Document ID mismatch",
        )

    upsert_redaction_decisions(
        document_id=document_id,
        decisions_json=request.model_dump(),
    )

    return {
        "documentId": document_id,
        "status": "saved",
    }


@router.post("/{document_id}/apply-redactions")
async def apply_redactions(
    document_id: str,
    request: ApplyRedactionsRequest,
    background_tasks: BackgroundTasks,
):
    document = get_document_or_404(document_id)

    if document_id != request.documentId:

        logger.warning(
            "redaction_request_rejected",
            extra={
                "event": "redaction_request_rejected",
                "reason": "document_id_mismatch",
                "document_id": document_id,
                "request_document_id": request.documentId,
            },
        )
        raise HTTPException(status_code=400, detail="Document ID mismatch")

    if not request.decisions:
        logger.warning(
            "redaction_request_rejected",
            extra={
                "event": "redaction_request_rejected",
                "reason": "no_decisions_supplied",
                "document_id": document_id,
            },
        )
        raise HTTPException(status_code=400, detail="No redaction decisions supplied")

    logger.info(
        "redaction_started",
        extra={
            "event": "redaction_started",
            "document_id": document_id,
            "redaction_count": len(request.decisions),
        },
    )

    update_document_record(
        document_id,
        status="applying_redactions",
        redaction_started_at=datetime.now(timezone.utc),
        redaction_completed_at=None,
        clear_error=True,
    )

    background_tasks.add_task(
        apply_redactions_pipeline,
        document_id=document_id,
        request=request,
    )

    return {
        "documentId": document_id,
        "status": "applying_redactions",
    }
