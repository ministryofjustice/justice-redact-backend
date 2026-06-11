from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services.document_store import get_document_or_404
from app.services.file_store import (
    export_pdf_path,
    vetted_pdf_path,
    processed_review_path,
    read_json,
)

router = APIRouter(prefix="/documents", tags=["exports"])


@router.get("/{document_id}/export")
async def get_document_export(document_id: str):
    document = get_document_or_404(document_id)

    export_path = export_pdf_path(document_id)
    vetted_path = vetted_pdf_path(document_id)

    if not export_path.exists():
        raise HTTPException(status_code=404, detail="Redacted file not found")

    if not vetted_path.exists():
        raise HTTPException(status_code=404, detail="Vetted file not found")

    page_count = None
    processed_path = processed_review_path(document_id)
    if processed_path.exists():
        processed_data = read_json(processed_path)
        page_count = processed_data.get("summary", {}).get("totalPages")

    return {
        "documentId": document_id,
        "filename": document["filename"],
        "status": "redaction_complete",
        "redactedExportUrl": f"{router.prefix}/{document_id}/redacted-file",
        "vettedExportUrl": f"{router.prefix}/{document_id}/vetted-file",
        "pageCount": page_count,
    }


@router.get("/{document_id}/redacted-file")
async def download_redacted_file(document_id: str):
    document = get_document_or_404(document_id)

    export_path = export_pdf_path(document_id)
    if not export_path.exists():
        raise HTTPException(status_code=404, detail="Exported file not found")

    original_name = document.get("filename", "redacted.pdf")
    download_name = original_name.replace(".pdf", "_redacted.pdf")

    return FileResponse(
        path=export_path,
        media_type="application/pdf",
        filename=download_name,
    )


@router.get("/{document_id}/vetted-file")
async def download_vetted_file(document_id: str):
    document = get_document_or_404(document_id)

    vetted_path = vetted_pdf_path(document_id)

    if not vetted_path.exists():
        raise HTTPException(status_code=404, detail="Vetted file not found")

    original_name = document.get("filename", "vetted.pdf")
    download_name = original_name.replace(".pdf", "_vetted.pdf")

    return FileResponse(
        path=vetted_path,
        media_type="application/pdf",
        filename=download_name,
    )
