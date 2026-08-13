from uuid import uuid4
from app.logging_config import logger
from app.models.document_requests import ProcessDocumentRequest
from app.services.sqs_service import send_document_processing_message
from app.services.document_store import (
    create_document_record,
    get_document_or_404,
    update_document_record,
    mark_document_processing_queued,
    try_start_document_processing_enqueue,
)
from app.services.file_store import save_upload_file
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from app.services.s3_service import get_object_from_s3
from app.services.s3_keys import preview_image_key

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    document_type: Literal["nomis", "dps", "unidentified"] = Form(
        ...,
        alias="documentType",
    ),
):
    uploaded_filename = file.filename or "document.pdf"

    if file.content_type != "application/pdf":
        logger.warning(
            "document_upload_rejected",
            extra={
                "event": "document_upload_rejected",
                "reason": "invalid_content_type",
                "content_type": file.content_type,
                "uploaded_filename": uploaded_filename,
            },
        )
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    document_id = str(uuid4())

    save_upload_file(
        file=file,
        document_id=document_id,
    )

    create_document_record(
        document_id=document_id,
        filename=uploaded_filename,
        document_type=document_type,
    )

    logger.info(
        "document_uploaded",
        extra={
            "event": "document_uploaded",
            "document_id": document_id,
            "uploaded_filename": uploaded_filename,
            "document_type": document_type,
        },
    )

    return {
        "documentId": document_id,
        "status": "uploaded",
    }


@router.post("/{document_id}/process")
async def process_document(
    document_id: str,
    request: ProcessDocumentRequest,
):
    document = get_document_or_404(document_id)

    if document["status"] in {
        "enqueueing",
        "queued",
        "processing",
        "retrying",
        "ready_for_review",
    }:
        return {
            "documentId": document_id,
            "status": document["status"],
        }

    job_id = str(uuid4())

    started = try_start_document_processing_enqueue(
        document_id=document_id,
        job_id=job_id,
        subject_name=request.subjectName,
        subject_prison_number=request.subjectPrisonNumber,
        other_phrases=request.otherPhrases,
    )

    if not started:
        current_document = get_document_or_404(document_id)

        return {
            "documentId": document_id,
            "status": current_document["status"],
        }

    try:
        message_id = send_document_processing_message(
            document_id=document_id,
            job_id=job_id,
        )
    except Exception:
        logger.exception(
            "document_processing_enqueue_failed",
            extra={
                "event": "document_processing_enqueue_failed",
                "document_id": document_id,
                "job_id": job_id,
            },
        )

        update_document_record(
            document_id,
            status="enqueue_failed",
        )

        raise HTTPException(
            status_code=503,
            detail="The document could not be queued for processing",
        )

    mark_document_processing_queued(
        document_id=document_id,
        job_id=job_id,
    )

    logger.info(
        "document_processing_queued",
        extra={
            "event": "document_processing_queued",
            "document_id": document_id,
            "job_id": job_id,
            "sqs_message_id": message_id,
        },
    )

    return {
        "documentId": document_id,
        "status": "queued",
    }


@router.get("/{document_id}/images/{image_id}.png")
async def get_document_image_preview(document_id: str, image_id: str):
    key = preview_image_key(
        document_id,
        image_id,
    )

    try:
        image_bytes = get_object_from_s3(key)
    except Exception:

        logger.warning(
            "document_image_preview_not_found",
            extra={
                "event": "document_image_preview_not_found",
                "document_id": document_id,
                "image_id": image_id,
            },
        )
        raise HTTPException(status_code=404, detail="Image preview not found")

    return Response(
        content=image_bytes,
        media_type="image/png",
    )


@router.get("/{document_id}/status")
async def get_document_status(document_id: str):
    return get_document_or_404(document_id)
