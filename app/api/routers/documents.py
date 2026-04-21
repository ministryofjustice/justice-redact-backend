import asyncio
from uuid import uuid4

from fastapi import APIRouter, File, UploadFile

from app.models.document_requests import ProcessDocumentRequest
from app.services.document_processing_service import process_document_pipeline
from app.services.document_store import create_document_record, get_document_or_404
from app.services.file_store import save_upload_file, upload_pdf_path

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    document_id = str(uuid4())
    save_upload_file(file, upload_pdf_path(document_id))
    create_document_record(
        document_id=document_id, filename=file.filename or "document.pdf"
    )

    return {
        "documentId": document_id,
        "status": "uploaded",
    }


@router.post("/{document_id}/process")
async def process_document(document_id: str, request: ProcessDocumentRequest):
    document = get_document_or_404(document_id)

    document["subjectName"] = request.subjectName
    document["subjectPrisonNumber"] = request.subjectPrisonNumber
    document["otherPhrases"] = request.otherPhrases
    document["status"] = "processing"

    asyncio.create_task(process_document_pipeline(document_id))

    return {
        "documentId": document_id,
        "status": "processing",
    }


@router.get("/{document_id}/status")
async def get_document_status(document_id: str):
    return get_document_or_404(document_id)
