from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.logging_config import logger
from app.services.document_store import get_document_or_404
from app.services.redaction_run_store import get_redaction_run
from app.services.s3_keys import (
    redaction_run_exempt_pdf_key,
    redaction_run_redacted_pdf_key,
    redaction_run_vetted_pdf_key,
)
from app.services.s3_service import get_object_from_s3, object_exists_in_s3

router = APIRouter(prefix="/documents", tags=["exports"])


def _get_completed_run(
    *,
    document_id: str,
    run_id: str,
) -> dict:
    redaction_run = get_redaction_run(run_id)

    if redaction_run is None or redaction_run.get("documentId") != document_id:
        raise HTTPException(
            status_code=404,
            detail="Redaction run not found",
        )

    if redaction_run.get("status") != "completed":
        raise HTTPException(
            status_code=409,
            detail="Redaction run is not available for export",
        )

    if redaction_run.get("pageCounts") is None:
        raise HTTPException(
            status_code=500,
            detail="Completed redaction run has no page counts",
        )

    return redaction_run


def _get_current_completed_run(
    *,
    document: dict,
    document_id: str,
    run_id: str,
) -> dict:
    redaction_run = _get_completed_run(
        document_id=document_id,
        run_id=run_id,
    )

    if document.get("currentRedactionRunId") != run_id:
        raise HTTPException(
            status_code=409,
            detail="Redaction run has been superseded",
        )

    if document.get("status") != "redaction_complete":
        raise HTTPException(
            status_code=409,
            detail="Redaction run is not available for export",
        )

    return redaction_run


@router.get("/{document_id}/redaction-runs/{run_id}/export")
async def get_document_export(
    document_id: str,
    run_id: str,
):
    document = get_document_or_404(document_id)

    redaction_run = _get_completed_run(
        document_id=document_id,
        run_id=run_id,
    )

    redacted_key = redaction_run_redacted_pdf_key(
        document_id,
        run_id,
    )

    vetted_key = redaction_run_vetted_pdf_key(
        document_id,
        run_id,
    )

    exempt_key = redaction_run_exempt_pdf_key(
        document_id,
        run_id,
    )

    if not object_exists_in_s3(redacted_key):
        logger.warning(
            "document_export_failed",
            extra={
                "event": "document_export_failed",
                "reason": "redacted_file_not_found",
                "document_id": document_id,
                "run_id": run_id,
            },
        )
        raise HTTPException(
            status_code=500,
            detail="Redacted file not found",
        )

    if not object_exists_in_s3(vetted_key):
        logger.warning(
            "document_export_failed",
            extra={
                "event": "document_export_failed",
                "reason": "vetted_file_not_found",
                "document_id": document_id,
                "run_id": run_id,
            },
        )
        raise HTTPException(
            status_code=500,
            detail="Vetted file not found",
        )

    exempt_exists = object_exists_in_s3(exempt_key)

    page_counts = redaction_run["pageCounts"]
    original_page_count = page_counts["original"]

    logger.info(
        "document_export_generated",
        extra={
            "event": "document_export_generated",
            "document_id": document_id,
            "run_id": run_id,
            "original_page_count": page_counts["original"],
            "exempt_page_count": page_counts["exempt"],
            "deleted_page_count": page_counts["deleted"],
            "redacted_page_count": page_counts["redacted"],
            "exempt_file_included": exempt_exists,
        },
    )

    return {
        "documentId": document_id,
        "runId": run_id,
        "filename": document["filename"],
        "status": "redaction_complete",
        "redactedExportUrl": (
            f"{router.prefix}/{document_id}" f"/redaction-runs/{run_id}/redacted-file"
        ),
        "vettedExportUrl": (
            f"{router.prefix}/{document_id}" f"/redaction-runs/{run_id}/vetted-file"
        ),
        "exemptExportUrl": (
            f"{router.prefix}/{document_id}" f"/redaction-runs/{run_id}/exempt-file"
            if exempt_exists
            else None
        ),
        "pageCount": original_page_count,
        "pageCounts": page_counts,
    }


@router.get("/{document_id}/redaction-runs/{run_id}/redacted-file")
async def download_redacted_file(
    document_id: str,
    run_id: str,
):
    document = get_document_or_404(document_id)

    _get_current_completed_run(
        document=document,
        document_id=document_id,
        run_id=run_id,
    )

    key = redaction_run_redacted_pdf_key(
        document_id,
        run_id,
    )

    if not object_exists_in_s3(key):
        raise HTTPException(
            status_code=500,
            detail="Exported file not found",
        )

    original_name = document.get("filename", "redacted.pdf")
    download_name = original_name.replace(".pdf", "_redacted.pdf")

    pdf_bytes = get_object_from_s3(key)

    logger.info(
        "document_file_downloaded",
        extra={
            "event": "document_file_downloaded",
            "document_id": document_id,
            "run_id": run_id,
            "file_kind": "redacted",
        },
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
        },
    )


@router.get("/{document_id}/redaction-runs/{run_id}/vetted-file")
async def download_vetted_file(
    document_id: str,
    run_id: str,
):
    document = get_document_or_404(document_id)

    _get_current_completed_run(
        document=document,
        document_id=document_id,
        run_id=run_id,
    )

    key = redaction_run_vetted_pdf_key(
        document_id,
        run_id,
    )

    if not object_exists_in_s3(key):
        raise HTTPException(
            status_code=500,
            detail="Vetted file not found",
        )

    original_name = document.get("filename", "vetted.pdf")
    download_name = original_name.replace(".pdf", "_vetted.pdf")

    pdf_bytes = get_object_from_s3(key)

    logger.info(
        "document_file_downloaded",
        extra={
            "event": "document_file_downloaded",
            "document_id": document_id,
            "run_id": run_id,
            "file_kind": "vetted",
        },
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
        },
    )


@router.get("/{document_id}/redaction-runs/{run_id}/exempt-file")
async def download_exempt_file(
    document_id: str,
    run_id: str,
):
    document = get_document_or_404(document_id)

    _get_current_completed_run(
        document=document,
        document_id=document_id,
        run_id=run_id,
    )

    key = redaction_run_exempt_pdf_key(
        document_id,
        run_id,
    )

    if not object_exists_in_s3(key):
        raise HTTPException(
            status_code=500,
            detail="Exempt file not found",
        )

    original_name = document.get("filename", "exempt.pdf")
    download_name = original_name.replace(".pdf", "_exempt.pdf")

    pdf_bytes = get_object_from_s3(key)

    logger.info(
        "document_file_downloaded",
        extra={
            "event": "document_file_downloaded",
            "document_id": document_id,
            "run_id": run_id,
            "file_kind": "exempt",
        },
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
        },
    )
