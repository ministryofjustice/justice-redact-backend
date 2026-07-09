import asyncio
from uuid import uuid4

from app.logging_config import logger
from app.models.document_requests import ProcessDocumentRequest
from app.services.document_processing_service import process_document_pipeline
from app.services.document_store import (
    create_document_record,
    get_document_or_404,
    update_document_record,
)
from app.services.file_store import save_upload_file
from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import Response
from app.services.s3_service import get_object_from_s3
from app.services.s3_keys import preview_image_key

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        logger.warning(
            "document_upload_rejected",
            extra={
                "event": "document_upload_rejected",
                "reason": "invalid_content_type",
                "content_type": file.content_type,
                # NOTE: filename is logged here (and in document_uploaded
                # below) because it's needed to debug upload issues, but
                # original filenames may themselves contain identifying
                # information (e.g. a person's name or case reference).
                # Confirm this is acceptable under this service's data
                # protection review before relying on it in production -
                # see the note in document_processing_service.py for why
                # subject name/prison number are handled differently
                # (never logged at all).
                "filename": file.filename,
            },
        )
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    document_id = str(uuid4())

    save_upload_file(
        file=file,
        document_id=document_id,
    )

    create_document_record(
        document_id=document_id, filename=file.filename or "document.pdf"
    )

    logger.info(
        "document_uploaded",
        extra={
            "event": "document_uploaded",
            "document_id": document_id,
            "filename": file.filename or "document.pdf",
        },
    )

    return {
        "documentId": document_id,
        "status": "uploaded",
    }


@router.post("/{document_id}/process")
async def process_document(document_id: str, request: ProcessDocumentRequest):
    get_document_or_404(document_id)

    update_document_record(
        document_id,
        status="processing",
        subject_name=request.subjectName,
        subject_prison_number=request.subjectPrisonNumber,
        other_phrases=request.otherPhrases,
    )

    # Logged here (request-accepted) as well as at the start of
    # process_document_pipeline in document_processing_service.py, since
    # that pipeline runs as a fire-and-forget background task - this event
    # confirms the request was accepted even if the background task is
    # slow to start.
    logger.info(
        "document_processing_started",
        extra={
            "event": "document_processing_started",
            "document_id": document_id,
        },
    )

    asyncio.create_task(process_document_pipeline(document_id))

    return {
        "documentId": document_id,
        "status": "processing",
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
        # Warning, not exception/error - a missing preview image is an
        # expected occurrence (e.g. still processing) rather than a bug,
        # so no need for a full stack trace here.
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