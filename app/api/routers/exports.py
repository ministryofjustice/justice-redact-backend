from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.services.document_store import get_document_or_404
from app.services.review_result_store import get_review_result
from app.services.s3_keys import exempt_pdf_key, redacted_pdf_key, vetted_pdf_key
from app.services.s3_service import get_object_from_s3, object_exists_in_s3

router = APIRouter(prefix="/documents", tags=["exports"])


@router.get("/{document_id}/export")
async def get_document_export(document_id: str):
    document = get_document_or_404(document_id)

    redacted_key = redacted_pdf_key(document_id)
    vetted_key = vetted_pdf_key(document_id)
    exempt_key = exempt_pdf_key(document_id)

    if not object_exists_in_s3(redacted_key):
        raise HTTPException(status_code=404, detail="Redacted file not found")

    if not object_exists_in_s3(vetted_key):
        raise HTTPException(status_code=404, detail="Vetted file not found")

    exempt_exists = object_exists_in_s3(exempt_key)

    page_count = None
    review_result = get_review_result(document_id)

    if review_result is not None:
        page_count = review_result.get("summary", {}).get("totalPages")

    return {
        "documentId": document_id,
        "filename": document["filename"],
        "status": "redaction_complete",
        "redactedExportUrl": f"{router.prefix}/{document_id}/redacted-file",
        "vettedExportUrl": f"{router.prefix}/{document_id}/vetted-file",
        "exemptExportUrl": (
            f"{router.prefix}/{document_id}/exempt-file" if exempt_exists else None
        ),
        "pageCount": page_count,
    }


@router.get("/{document_id}/redacted-file")
async def download_redacted_file(document_id: str):
    document = get_document_or_404(document_id)

    key = redacted_pdf_key(document_id)

    if not object_exists_in_s3(key):
        raise HTTPException(status_code=404, detail="Exported file not found")

    original_name = document.get("filename", "redacted.pdf")
    download_name = original_name.replace(".pdf", "_redacted.pdf")

    pdf_bytes = get_object_from_s3(key)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
        },
    )


@router.get("/{document_id}/vetted-file")
async def download_vetted_file(document_id: str):
    document = get_document_or_404(document_id)

    key = vetted_pdf_key(document_id)

    if not object_exists_in_s3(key):
        raise HTTPException(status_code=404, detail="Vetted file not found")

    original_name = document.get("filename", "vetted.pdf")
    download_name = original_name.replace(".pdf", "_vetted.pdf")

    pdf_bytes = get_object_from_s3(key)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
        },
    )


@router.get("/{document_id}/exempt-file")
async def download_exempt_file(document_id: str):
    document = get_document_or_404(document_id)

    key = exempt_pdf_key(document_id)

    if not object_exists_in_s3(key):
        raise HTTPException(status_code=404, detail="Exempt file not found")

    original_name = document.get("filename", "exempt.pdf")
    download_name = original_name.replace(".pdf", "_exempt.pdf")

    pdf_bytes = get_object_from_s3(key)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
        },
    )
