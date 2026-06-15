import asyncio
from uuid import uuid4

from app.models.document_requests import ProcessDocumentRequest
from app.services.document_processing_service import process_document_pipeline
from app.services.document_store import (
    create_document_record,
    get_document_or_404,
    update_document_record,
)
from app.services.file_store import save_upload_file, upload_pdf_path
from pathlib import Path
from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    document_id = str(uuid4())
    save_upload_file(
        file,
        upload_pdf_path(document_id),
        document_id,
    )
    create_document_record(
        document_id=document_id, filename=file.filename or "document.pdf"
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

    asyncio.create_task(process_document_pipeline(document_id))

    return {
        "documentId": document_id,
        "status": "processing",
    }


@router.get("/{document_id}/images/{image_id}.png")
async def get_document_image_preview(document_id: str, image_id: str):
    image_path = Path("data/processed") / document_id / "images" / f"{image_id}.png"

    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image preview not found")

    return FileResponse(
        image_path,
        media_type="image/png",
        filename=f"{image_id}.png",
    )


@router.get("/{document_id}/status")
async def get_document_status(document_id: str):
    return get_document_or_404(document_id)
