from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time

import pymupdf

from app.logging_config import logger
from app.services.document_store import get_document
from app.services.review_result_store import (
    publish_review_result_if_processing_owner,
)
from app.services.s3_keys import (
    document_geometry_chunk_key,
    document_geometry_manifest_key,
    preview_image_key,
)
from app.services.s3_service import (
    download_file_from_s3,
    upload_file_to_s3,
    upload_json_to_s3,
)
from justice_redact.detection.review import (
    detect_for_review_chunk_with_document,
)
from justice_redact.detection.runtime import build_detection_runtime
from justice_redact.pdf_handler.images import render_pdf_region_to_png


PDF_PROCESSING_CHUNK_SIZE = 100


class DocumentProcessingCancelled(Exception):
    pass


def assert_processing_active(
    is_processing_active,
) -> None:
    if not is_processing_active():
        raise DocumentProcessingCancelled(
            "Document processing is no longer authoritative"
        )


def _log_stage(
    stage: str,
    document_id: str,
    duration_s: float,
    **extra,
) -> None:
    """
    Central helper so every pipeline stage logs the same shape.

    IMPORTANT: this function - and every logger call in this file - must
    NEVER be passed subjectName, subjectPrisonNumber, or otherPhrases via
    **extra. This pipeline processes highly sensitive data and logging that
    data into OpenSearch should only ever be done deliberately.
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


def build_page_chunks(
    total_pages: int,
    chunk_size: int,
) -> list[dict]:
    chunks = []

    for chunk_index, page_start in enumerate(
        range(1, total_pages + 1, chunk_size),
        start=1,
    ):
        page_end = min(
            page_start + chunk_size - 1,
            total_pages,
        )

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
    *,
    job_id: str,
    claim_id: str,
    is_processing_active=lambda: True,
) -> None:
    """
    Download and process a document in page chunks, generate review data
    and preview assets, and publish the final review result.

    Sensitive subject details must never be written to application logs.
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

    temp_pdf_path = Path("/tmp") / f"{document_id}.pdf"
    image_preview_dir = Path("/tmp") / "processed" / document_id / "images"

    try:
        assert_processing_active(is_processing_active)

        start = time.perf_counter()

        download_file_from_s3(
            (f"documents/{document_id}/original/" f"{document['filename']}"),
            temp_pdf_path,
        )

        _log_stage(
            "download_file_from_s3",
            document_id,
            time.perf_counter() - start,
        )

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

        resolved_document_type = document["documentType"]

        if resolved_document_type == "unidentified":
            resolved_document_type = "nomis"

        detection_runtime = build_detection_runtime(
            doc_type=resolved_document_type,
            subject_name=document["subjectName"],
            subject_prison_number=document["subjectPrisonNumber"],
            extra_allow_list=other_phrases_list,
        )

        _log_stage(
            "build_detection_runtime",
            document_id,
            time.perf_counter() - start,
        )

        combined_pages = []
        combined_findings = []
        total_text_items = 0

        image_preview_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        preview_count = 0

        for chunk in chunks:
            assert_processing_active(is_processing_active)

            chunk_index = chunk["chunkIndex"]
            page_start = chunk["pageStart"]
            page_end = chunk["pageEnd"]

            chunk_start = time.perf_counter()

            (
                chunk_result,
                chunk_document,
            ) = detect_for_review_chunk_with_document(
                pdf_path=pdf_path,
                page_start=page_start,
                page_end=page_end,
                total_page_count=page_count,
                subject_name=document["subjectName"],
                subject_prison_number=document["subjectPrisonNumber"],
                other_phrases=other_phrases_list,
                runtime=detection_runtime,
            )

            assert_processing_active(is_processing_active)

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
                document_geometry_chunk_key(
                    document_id,
                    chunk_index,
                ),
            )

            _log_stage(
                "upload_document_geometry_chunk",
                document_id,
                time.perf_counter() - start,
                chunk_index=chunk_index,
                chunk_count=len(chunks),
            )

            combined_pages.extend(chunk_result.get("pages", []))

            for finding in chunk_result.get(
                "findings",
                [],
            ):
                finding["id"] = "finding_" f"{len(combined_findings) + 1:06d}"
                combined_findings.append(finding)

            total_text_items += chunk_result.get(
                "summary",
                {},
            ).get(
                "totalTextItems",
                0,
            )

            start = time.perf_counter()

            for page in chunk_result.get(
                "pages",
                [],
            ):
                for image in page.get(
                    "images",
                    [],
                ):
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
                        f"/documents/{document_id}" f"/images/{image['imageId']}.png"
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
                "subjectName": (document["subjectName"] or ""),
                "subjectPrisonNumber": (document["subjectPrisonNumber"] or ""),
                "otherPhrases": other_phrases_list,
            },
            "pages": combined_pages,
            "findings": combined_findings,
            "documentId": document_id,
            "filename": document["filename"],
            "status": "ready_for_review",
        }

        assert_processing_active(is_processing_active)

        # Measure only the size of the final payload.
        # Do not log any review JSON contents because
        # they contain sensitive SAR data.
        review_json_bytes = len(
            json.dumps(
                result,
                separators=(",", ":"),
            ).encode("utf-8")
        )

        logger.info(
            "document_processing_review_result_size",
            extra={
                "event": ("document_processing_" "review_result_size"),
                "document_id": document_id,
                "total_pages": page_count,
                "total_findings": len(combined_findings),
                "review_json_bytes": (review_json_bytes),
                "review_json_mb": round(
                    review_json_bytes / (1024 * 1024),
                    2,
                ),
            },
        )

        # Start this timer immediately before the
        # final DB publication so the timing measures
        # only the publication transaction.
        start = time.perf_counter()

        published = publish_review_result_if_processing_owner(
            document_id=document_id,
            job_id=job_id,
            claim_id=claim_id,
            review_json=result,
            completed_at=datetime.now(timezone.utc),
        )

        if not published:
            raise DocumentProcessingCancelled(
                "Document processing lost ownership " "before final publication"
            )

        _log_stage(
            "upsert_review_result",
            document_id,
            time.perf_counter() - start,
        )

        logger.info(
            "document_processing_completed",
            extra={
                "event": ("document_processing_completed"),
                "document_id": document_id,
                "total_pages": page_count,
                "total_text_items": (total_text_items),
                "total_findings": len(combined_findings),
                "preview_count": preview_count,
                "duration_ms": round(
                    (time.perf_counter() - pipeline_start) * 1000,
                    2,
                ),
            },
        )

    except Exception as exc:
        # Do not use logger.exception() here.
        #
        # SQLAlchemy/psycopg tracebacks may contain
        # the SQL statement or bound parameters.
        # The bound parameters can include review_json,
        # which contains sensitive SAR information.
        original_error = getattr(
            exc,
            "orig",
            None,
        )

        logger.error(
            "document_processing_attempt_failed",
            extra={
                "event": ("document_processing_" "attempt_failed"),
                "document_id": document_id,
                "error_type": type(exc).__name__,
                "db_error_type": (
                    type(original_error).__name__
                    if original_error is not None
                    else None
                ),
                "sqlstate": getattr(
                    original_error,
                    "sqlstate",
                    None,
                ),
                "connection_invalidated": getattr(
                    exc,
                    "connection_invalidated",
                    None,
                ),
                "duration_ms": round(
                    (time.perf_counter() - pipeline_start) * 1000,
                    2,
                ),
            },
        )

        raise

    finally:
        temp_pdf_path.unlink(missing_ok=True)

        shutil.rmtree(
            image_preview_dir.parent,
            ignore_errors=True,
        )
