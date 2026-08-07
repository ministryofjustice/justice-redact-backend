from pathlib import Path
import pymupdf
from datetime import datetime, timezone
from app.logging_config import logger
from app.services.document_store import get_document, update_document_record
from app.services.review_result_store import upsert_review_result
from app.services.s3_service import (
    download_file_from_s3,
    upload_file_to_s3,
    upload_json_to_s3,
)
from app.services.s3_keys import (
    document_geometry_chunk_key,
    document_geometry_manifest_key,
    preview_image_key,
)
from justice_redact.detection.runtime import build_detection_runtime
from justice_redact.detection.review import detect_for_review_chunk_with_document
from justice_redact.pdf_handler.images import render_pdf_region_to_png
import time


PDF_PROCESSING_CHUNK_SIZE = 100


def _log_stage(stage: str, document_id: str, duration_s: float, **extra) -> None:
    """
    Central helper so every pipeline stage logs the same shape (previously
    each stage had its own `print(f"[TIMING] ...")` line - this replaces
    all of them with one structured event per stage, filterable by `stage`
    in OpenSearch).

    IMPORTANT: this function - and every logger call in this file - must
    NEVER be passed subjectName, subjectPrisonNumber, or otherPhrases via
    **extra. This pipeline processes the most sensitive data in the whole
    service (a person's identity and prison number); logging it into
    OpenSearch, a separate data store with its own retention/access
    characteristics from the primary RDS/S3 data, should be a deliberate,
    reviewed decision - not a side-effect of adding observability. This is
    enforced here by simply never passing those fields in, at every call
    site below.
    """
    logger.info(
        "document_processing_stage",
        extra={
            "event": "document_processing_stage",
            "stage": stage,
            "document_id": document_id,
            "duration_ms": round(duration_s * 1000, 2),
            **extra,
        },
    )


def get_pdf_page_count(pdf_path: Path) -> int:
    doc = pymupdf.open(str(pdf_path))

    try:
        return doc.page_count
    finally:
        doc.close()


def build_page_chunks(total_pages: int, chunk_size: int) -> list[dict]:
    chunks = []

    for chunk_index, page_start in enumerate(
        range(1, total_pages + 1, chunk_size),
        start=1,
    ):
        page_end = min(page_start + chunk_size - 1, total_pages)

        chunks.append(
            {
                "chunkIndex": chunk_index,
                "pageStart": page_start,
                "pageEnd": page_end,
            }
        )

    return chunks


def process_document_pipeline(
    document_id: str,
    document_type: str,
) -> None:
    """
    Background task (kicked off via asyncio.create_task from
    app/api/routers/documents.py's /process endpoint) that downloads the
    original PDF, runs detection in page chunks, renders preview images,
    and stores the combined review result.

    Logging strategy: every stage that was previously a `print(f"[TIMING]
    ...")` line now goes through _log_stage (see docstring above for why
    subject details are never included). Pipeline-level start/completion/
    failure get their own dedicated events in addition to the per-stage
    timing events, so both "how long did this take" and "did it succeed"
    are independently queryable in OpenSearch.
    """
    pipeline_start = time.perf_counter()
    document = get_document(document_id)

    if not document:

        logger.warning(
            "document_processing_skipped",
            extra={
                "event": "document_processing_skipped",
                "reason": "document_not_found",
                "document_id": document_id,
            },
        )
        return

    update_document_record(
        document_id,
        status="processing",
        processing_started_at=datetime.now(timezone.utc),
        processing_completed_at=None,
        clear_error=True,
    )

    try:
        temp_pdf_path = Path("/tmp") / f"{document_id}.pdf"

        start = time.perf_counter()

        download_file_from_s3(
            f"documents/{document_id}/original/{document['filename']}",
            temp_pdf_path,
        )

        _log_stage("download_file_from_s3", document_id, time.perf_counter() - start)

        page_count = get_pdf_page_count(temp_pdf_path)
        chunks = build_page_chunks(
            total_pages=page_count,
            chunk_size=PDF_PROCESSING_CHUNK_SIZE,
        )

        _log_stage(
            "chunk_plan",
            document_id,
            0,
            total_pages=page_count,
            chunk_size=PDF_PROCESSING_CHUNK_SIZE,
            chunk_count=len(chunks),
        )

        pdf_path = str(temp_pdf_path)

        other_phrases_list = [
            phrase.strip()
            for phrase in document["otherPhrases"].split(",")
            if phrase.strip()
        ]

        start = time.perf_counter()

        document_type = document["documentType"]

        if document_type == "unidentified":
            document_type = "nomis"

        detection_runtime = build_detection_runtime(
            doc_type=document_type,
            subject_name=document["subjectName"],
            subject_prison_number=document["subjectPrisonNumber"],
            extra_allow_list=other_phrases_list,
        )

        _log_stage("build_detection_runtime", document_id, time.perf_counter() - start)

        combined_pages = []
        combined_findings = []
        total_text_items = 0

        image_preview_dir = Path("/tmp") / "processed" / document_id / "images"
        image_preview_dir.mkdir(parents=True, exist_ok=True)

        preview_count = 0

        for chunk in chunks:
            chunk_index = chunk["chunkIndex"]
            page_start = chunk["pageStart"]
            page_end = chunk["pageEnd"]

            chunk_start = time.perf_counter()

            chunk_result, chunk_document = detect_for_review_chunk_with_document(
                pdf_path=pdf_path,
                page_start=page_start,
                page_end=page_end,
                total_page_count=page_count,
                subject_name=document["subjectName"],
                subject_prison_number=document["subjectPrisonNumber"],
                other_phrases=other_phrases_list,
                runtime=detection_runtime,
            )

            _log_stage(
                "detect_for_review_chunk",
                document_id,
                time.perf_counter() - chunk_start,
                chunk_index=chunk_index,
                chunk_count=len(chunks),
                page_start=page_start,
                page_end=page_end,
            )

            start = time.perf_counter()

            upload_json_to_s3(
                chunk_document.model_dump(),
                document_geometry_chunk_key(document_id, chunk_index),
            )

            _log_stage(
                "upload_document_geometry_chunk",
                document_id,
                time.perf_counter() - start,
                chunk_index=chunk_index,
                chunk_count=len(chunks),
            )

            combined_pages.extend(chunk_result.get("pages", []))

            for finding in chunk_result.get("findings", []):
                finding["id"] = f"finding_{len(combined_findings) + 1:06d}"
                combined_findings.append(finding)

            total_text_items += chunk_result.get("summary", {}).get(
                "totalTextItems",
                0,
            )

            start = time.perf_counter()

            for page in chunk_result.get("pages", []):
                for image in page.get("images", []):
                    bbox = image.get("bbox")

                    if not bbox:
                        continue

                    output_path = image_preview_dir / f"{image['imageId']}.png"

                    render_pdf_region_to_png(
                        pdf_path=pdf_path,
                        page_number=page["pageNumber"],
                        bbox=type(
                            "BBoxLike",
                            (),
                            {
                                "x0": bbox["x0"],
                                "y0": bbox["y0"],
                                "x1": bbox["x1"],
                                "y1": bbox["y1"],
                            },
                        )(),
                        output_path=output_path,
                    )

                    preview_key = preview_image_key(
                        document_id,
                        image["imageId"],
                    )

                    upload_file_to_s3(
                        output_path,
                        preview_key,
                    )

                    preview_count += 1

                    image["imageUrl"] = (
                        f"/documents/{document_id}/images/{image['imageId']}.png"
                    )

            _log_stage(
                "preview_generation_and_upload_chunk",
                document_id,
                time.perf_counter() - start,
                chunk_index=chunk_index,
                chunk_count=len(chunks),
            )

            del chunk_result
            del chunk_document

        manifest = {
            "chunkSize": PDF_PROCESSING_CHUNK_SIZE,
            "totalPages": page_count,
            "chunks": chunks,
        }

        start = time.perf_counter()

        upload_json_to_s3(
            manifest,
            document_geometry_manifest_key(document_id),
        )

        _log_stage(
            "upload_document_geometry_manifest",
            document_id,
            time.perf_counter() - start,
        )

        result = {
            "summary": {
                "totalPages": page_count,
                "totalTextItems": total_text_items,
                "totalFindings": len(combined_findings),
            },
            "subjectDetails": {
                "subjectName": document["subjectName"] or "",
                "subjectPrisonNumber": document["subjectPrisonNumber"] or "",
                "otherPhrases": other_phrases_list,
            },
            "pages": combined_pages,
            "findings": combined_findings,
            "documentId": document_id,
            "filename": document["filename"],
            "status": "ready_for_review",
        }

        start = time.perf_counter()

        upsert_review_result(
            document_id=document_id,
            review_json=result,
        )

        _log_stage("upsert_review_result", document_id, time.perf_counter() - start)

        update_document_record(
            document_id,
            status="ready_for_review",
            processing_completed_at=datetime.now(timezone.utc),
        )

        logger.info(
            "document_processing_completed",
            extra={
                "event": "document_processing_completed",
                "document_id": document_id,
                "total_pages": page_count,
                "total_text_items": total_text_items,
                "total_findings": len(combined_findings),
                "preview_count": preview_count,
                "duration_ms": round((time.perf_counter() - pipeline_start) * 1000, 2),
            },
        )

    except Exception as exc:

        logger.exception(
            "document_processing_failed",
            extra={
                "event": "document_processing_failed",
                "document_id": document_id,
                "error": str(exc),
                "duration_ms": round((time.perf_counter() - pipeline_start) * 1000, 2),
            },
        )

        update_document_record(
            document_id,
            status="failed",
            processing_completed_at=datetime.now(timezone.utc),
            error_message=str(exc),
        )
