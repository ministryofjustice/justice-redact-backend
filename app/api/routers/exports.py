from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services.document_store import get_document_or_404
from app.services.file_store import export_pdf_path, processed_review_path, read_json

router = APIRouter(prefix="/documents", tags=["exports"])


@router.get("/{document_id}/export")
async def get_document_export(document_id: str):
    document = get_document_or_404(document_id)

    export_path = export_pdf_path(document_id)
    if not export_path.exists():
        raise HTTPException(status_code=404, detail="Exported file not found")

    page_count = None
    processed_path = processed_review_path(document_id)
    if processed_path.exists():
        processed_data = read_json(processed_path)
        page_count = processed_data.get("summary", {}).get("totalPages")

    return {
        "documentId": document_id,
        "filename": document["filename"],
        "status": "redaction_complete",
        "exportUrl": f"{router.prefix}/{document_id}/export-file",
        "pageCount": page_count,
    }


@router.get("/{document_id}/export-file")
async def download_export_file(document_id: str):
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
