import uuid

from fastapi import APIRouter, HTTPException

from app.logging_config import logger
from app.services.sqs_service import send_redaction_processing_message
from app.models.redaction_models import (
    ApplyRedactionsRequest,
    SaveRedactionDecisionsRequest,
)
from app.services.redaction_run_store import (
    cancel_redaction_run,
    create_redaction_run,
    fail_redaction_run_enqueue,
    mark_redaction_run_queued,
)
from app.services.document_store import get_document_or_404
from app.services.redaction_decision_store import (
    get_redaction_decision_state,
    save_redaction_decisions,
)

router = APIRouter(prefix="/documents", tags=["redactions"])


@router.get("/{document_id}/redaction-decisions")
async def get_document_redaction_decisions(document_id: str):
    get_document_or_404(document_id)

    return get_redaction_decision_state(document_id)


@router.put("/{document_id}/redaction-decisions")
async def save_document_redaction_decisions(
    document_id: str,
    request: SaveRedactionDecisionsRequest,
):
    get_document_or_404(document_id)

    if document_id != request.documentId:
        raise HTTPException(
            status_code=400,
            detail="Document ID mismatch",
        )

    result = save_redaction_decisions(
        document_id=document_id,
        decisions_json={
            "documentId": request.documentId,
            "decisions": [decision.model_dump() for decision in request.decisions],
        },
        expected_revision=request.expectedRevision,
    )

    if not result["saved"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Redaction decisions have changed",
                "currentRevision": result["revision"],
            },
        )

    return {
        "documentId": document_id,
        "status": "saved",
        "revision": result["revision"],
    }


@router.post("/{document_id}/apply-redactions")
async def apply_redactions(
    document_id: str,
    request: ApplyRedactionsRequest,
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

    run_id = str(uuid.uuid4())

    result = create_redaction_run(
        run_id=run_id,
        document_id=document_id,
        expected_review_revision=request.expectedRevision,
    )

    if not result["created"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Redaction decisions have changed",
                "currentRevision": result["currentRevision"],
            },
        )

    logger.info(
        "redaction_run_created",
        extra={
            "event": "redaction_run_created",
            "document_id": document_id,
            "run_id": run_id,
        },
    )

    try:
        message_id = send_redaction_processing_message(
            document_id=document_id,
            run_id=run_id,
        )
    except Exception:
        logger.exception(
            "redaction_run_enqueue_failed",
            extra={
                "event": "redaction_run_enqueue_failed",
                "document_id": document_id,
                "run_id": run_id,
            },
        )

        fail_redaction_run_enqueue(
            run_id=run_id,
            error_message="The redaction run could not be queued",
        )

        raise HTTPException(
            status_code=503,
            detail="The redactions could not be queued for processing",
        )

    queued = mark_redaction_run_queued(
        run_id=run_id,
    )

    if not queued:
        logger.warning(
            "redaction_run_superseded_during_enqueue",
            extra={
                "event": "redaction_run_superseded_during_enqueue",
                "document_id": document_id,
                "run_id": run_id,
            },
        )

        raise HTTPException(
            status_code=409,
            detail=(
                "This redaction run was superseded by a newer "
                "Apply Redactions request"
            ),
        )

    logger.info(
        "redaction_run_queued",
        extra={
            "event": "redaction_run_queued",
            "document_id": document_id,
            "run_id": run_id,
            "sqs_message_id": message_id,
        },
    )

    return {
        "documentId": document_id,
        "runId": run_id,
        "status": "queued",
    }


@router.post("/{document_id}/redaction-runs/{run_id}/cancel")
async def cancel_redactions(
    document_id: str,
    run_id: str,
):
    get_document_or_404(document_id)

    cancelled = cancel_redaction_run(
        document_id=document_id,
        run_id=run_id,
    )

    if not cancelled:
        raise HTTPException(
            status_code=409,
            detail=(
                "This redaction run cannot be cancelled because "
                "it is no longer the current active run"
            ),
        )

    logger.info(
        "redaction_run_cancelled",
        extra={
            "event": "redaction_run_cancelled",
            "document_id": document_id,
            "run_id": run_id,
        },
    )

    return {
        "documentId": document_id,
        "runId": run_id,
        "status": "cancelled",
    }
