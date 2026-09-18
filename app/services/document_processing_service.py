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
    document_review_chunk_key,
    document_review_manifest_key,
    document_review_search_chunk_key,
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

_CGROUP_MEMORY_CURRENT_PATH = Path("/sys/fs/cgroup/memory.current")
_CGROUP_MEMORY_PEAK_PATH = Path("/sys/fs/cgroup/memory.peak")
_CGROUP_MEMORY_MAX_PATH = Path("/sys/fs/cgroup/memory.max")
_CGROUP_MEMORY_STAT_PATH = Path("/sys/fs/cgroup/memory.stat")
_PROC_SELF_STATUS_PATH = Path("/proc/self/status")


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
    NEVER be passed subjectName, subjectPrisonNumber, otherPhrases, extracted
    text, findings content, or other sensitive SAR data via **extra.
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


def _read_cgroup_memory_bytes(path: Path) -> int | None:
    try:
        value = path.read_text().strip()

        if value == "max":
            return None

        return int(value)
    except (OSError, ValueError):
        return None


def _read_cgroup_memory_stat() -> dict[str, int]:
    """
    Read cgroup v2 memory.stat values.

    Values are bytes. If the file is unavailable or cannot be parsed,
    return an empty dictionary so memory instrumentation never interrupts
    document processing.
    """
    try:
        stats: dict[str, int] = {}

        for line in _CGROUP_MEMORY_STAT_PATH.read_text().splitlines():
            parts = line.split(maxsplit=1)

            if len(parts) != 2:
                continue

            key, value = parts

            try:
                stats[key] = int(value)
            except ValueError:
                continue

        return stats
    except OSError:
        return {}


def _read_process_memory_kb() -> dict[str, int]:
    """
    Read selected memory values for this worker process from /proc/self/status.

    Linux reports these fields in KiB. Missing/unparseable values are ignored.
    """
    wanted = {
        "VmRSS",
        "RssAnon",
        "RssFile",
        "RssShmem",
    }

    try:
        values: dict[str, int] = {}

        for line in _PROC_SELF_STATUS_PATH.read_text().splitlines():
            key, separator, remainder = line.partition(":")

            if not separator or key not in wanted:
                continue

            parts = remainder.strip().split()

            if not parts:
                continue

            try:
                values[key] = int(parts[0])
            except ValueError:
                continue

        return values
    except OSError:
        return {}


def _bytes_to_mb(value: int | None) -> float | None:
    if value is None:
        return None

    return round(value / (1024 * 1024), 2)


def _kb_to_mb(value: int | None) -> float | None:
    if value is None:
        return None

    return round(value / 1024, 2)


def _log_memory_snapshot(
    *,
    point: str,
    document_id: str,
    chunk_index: int,
    chunk_count: int,
    combined_findings_count: int,
    analyser_cache_size: int,
    postprocessor_cache_size: int,
) -> None:
    """
    Log non-sensitive worker/container memory diagnostics.

    cgroup values reflect the memory accounting Kubernetes uses when enforcing
    the worker memory limit. /proc/self/status values help distinguish process
    RSS from file-backed/container-level memory.

    This helper must never receive document text, findings content, subject
    details, or any other SAR data.
    """
    current_bytes = _read_cgroup_memory_bytes(
        _CGROUP_MEMORY_CURRENT_PATH,
    )
    peak_bytes = _read_cgroup_memory_bytes(
        _CGROUP_MEMORY_PEAK_PATH,
    )
    limit_bytes = _read_cgroup_memory_bytes(
        _CGROUP_MEMORY_MAX_PATH,
    )

    memory_stat = _read_cgroup_memory_stat()
    process_memory = _read_process_memory_kb()

    logger.info(
        "document_processing_memory",
        extra={
            "event": "document_processing_memory",
            "point": point,
            "document_id": document_id,
            "chunk_index": chunk_index,
            "chunk_count": chunk_count,
            "memory_current_mb": _bytes_to_mb(current_bytes),
            "memory_peak_mb": _bytes_to_mb(peak_bytes),
            "memory_limit_mb": _bytes_to_mb(limit_bytes),
            "memory_anon_mb": _bytes_to_mb(
                memory_stat.get("anon"),
            ),
            "memory_file_mb": _bytes_to_mb(
                memory_stat.get("file"),
            ),
            "memory_kernel_mb": _bytes_to_mb(
                memory_stat.get("kernel"),
            ),
            "process_rss_mb": _kb_to_mb(
                process_memory.get("VmRSS"),
            ),
            "process_rss_anon_mb": _kb_to_mb(
                process_memory.get("RssAnon"),
            ),
            "process_rss_file_mb": _kb_to_mb(
                process_memory.get("RssFile"),
            ),
            "process_rss_shmem_mb": _kb_to_mb(
                process_memory.get("RssShmem"),
            ),
            "combined_findings_count": combined_findings_count,
            "analyser_cache_size": analyser_cache_size,
            "postprocessor_cache_size": postprocessor_cache_size,
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


def build_review_search_pages(
    review_pages: list[dict],
) -> list[dict]:
    search_pages = []

    for page in review_pages:
        search_tables = []

        for table in page.get("tables", []):
            search_rows = []

            for row in table.get("rows", []):
                search_cells = []

                for cell in row.get("cells", []):
                    search_cells.append(
                        {
                            "cellId": cell["cellId"],
                            "tableId": (cell.get("tableId") or table["tableId"]),
                            "rowIndex": cell.get(
                                "rowIndex",
                                row.get("rowIndex", 0),
                            ),
                            "colIndex": cell.get(
                                "colIndex",
                                0,
                            ),
                            "text": cell.get(
                                "text",
                                "",
                            ),
                            "renderText": cell.get(
                                "text",
                                "",
                            ),
                            "bbox": None,
                            "isHeader": bool(
                                cell.get(
                                    "isHeader",
                                    False,
                                )
                            ),
                            "isNumeric": bool(
                                cell.get(
                                    "isNumeric",
                                    False,
                                )
                            ),
                        }
                    )

                search_rows.append(
                    {
                        "rowIndex": row.get(
                            "rowIndex",
                            0,
                        ),
                        "cells": search_cells,
                    }
                )

            search_tables.append(
                {
                    "tableId": table["tableId"],
                    "bbox": None,
                    "rows": search_rows,
                }
            )

        search_pages.append(
            {
                "pageNumber": page["pageNumber"],
                "pageId": page.get("pageId"),
                "textItems": [
                    {
                        "itemId": item["itemId"],
                        "text": item.get(
                            "text",
                            "",
                        ),
                        "renderText": item.get(
                            "text",
                            "",
                        ),
                        "bbox": None,
                    }
                    for item in page.get(
                        "textItems",
                        [],
                    )
                ],
                "tables": search_tables,
                "images": [],
            }
        )

    return search_pages


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

            _log_memory_snapshot(
                point="before_chunk",
                document_id=document_id,
                chunk_index=chunk_index,
                chunk_count=len(chunks),
                combined_findings_count=len(combined_findings),
                analyser_cache_size=len(detection_runtime.analyser_cache),
                postprocessor_cache_size=len(detection_runtime.postprocessor_cache),
            )

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

            _log_memory_snapshot(
                point="after_detection",
                document_id=document_id,
                chunk_index=chunk_index,
                chunk_count=len(chunks),
                combined_findings_count=len(combined_findings),
                analyser_cache_size=len(detection_runtime.analyser_cache),
                postprocessor_cache_size=len(detection_runtime.postprocessor_cache),
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

            _log_memory_snapshot(
                point="after_geometry_upload",
                document_id=document_id,
                chunk_index=chunk_index,
                chunk_count=len(chunks),
                combined_findings_count=len(combined_findings),
                analyser_cache_size=len(detection_runtime.analyser_cache),
                postprocessor_cache_size=len(detection_runtime.postprocessor_cache),
            )

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

            review_chunk = {
                "chunkIndex": chunk_index,
                "pageStart": page_start,
                "pageEnd": page_end,
                "pages": chunk_result.get(
                    "pages",
                    [],
                ),
            }

            start = time.perf_counter()

            upload_json_to_s3(
                review_chunk,
                document_review_chunk_key(
                    document_id,
                    chunk_index,
                ),
            )

            _log_stage(
                "upload_document_review_chunk",
                document_id,
                time.perf_counter() - start,
                chunk_index=chunk_index,
                chunk_count=len(chunks),
                page_start=page_start,
                page_end=page_end,
            )

            search_pages = build_review_search_pages(
                chunk_result.get(
                    "pages",
                    [],
                )
            )

            search_chunk = {
                "chunkIndex": chunk_index,
                "pageStart": page_start,
                "pageEnd": page_end,
                "pages": search_pages,
            }

            start = time.perf_counter()

            upload_json_to_s3(
                search_chunk,
                document_review_search_chunk_key(
                    document_id,
                    chunk_index,
                ),
            )

            _log_stage(
                "upload_document_review_search_chunk",
                document_id,
                time.perf_counter() - start,
                chunk_index=chunk_index,
                chunk_count=len(chunks),
                page_start=page_start,
                page_end=page_end,
            )

            _log_memory_snapshot(
                point="before_cleanup",
                document_id=document_id,
                chunk_index=chunk_index,
                chunk_count=len(chunks),
                combined_findings_count=len(combined_findings),
                analyser_cache_size=len(detection_runtime.analyser_cache),
                postprocessor_cache_size=len(detection_runtime.postprocessor_cache),
            )

            del review_chunk
            del search_chunk
            del search_pages
            del chunk_result
            del chunk_document

            _log_memory_snapshot(
                point="after_cleanup",
                document_id=document_id,
                chunk_index=chunk_index,
                chunk_count=len(chunks),
                combined_findings_count=len(combined_findings),
                analyser_cache_size=len(detection_runtime.analyser_cache),
                postprocessor_cache_size=len(detection_runtime.postprocessor_cache),
            )

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

        start = time.perf_counter()

        upload_json_to_s3(
            manifest,
            document_review_manifest_key(document_id),
        )

        _log_stage(
            "upload_document_review_manifest",
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
            "pages": [],
            "findings": combined_findings,
            "documentId": document_id,
            "filename": document["filename"],
            "status": "ready_for_review",
        }

        assert_processing_active(is_processing_active)

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
                "review_json_bytes": review_json_bytes,
                "review_json_mb": round(
                    review_json_bytes / (1024 * 1024),
                    2,
                ),
            },
        )

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
                "event": "document_processing_completed",
                "document_id": document_id,
                "total_pages": page_count,
                "total_text_items": total_text_items,
                "total_findings": len(combined_findings),
                "preview_count": preview_count,
                "duration_ms": round(
                    (time.perf_counter() - pipeline_start) * 1000,
                    2,
                ),
            },
        )

    except Exception as exc:

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
        temp_pdf_path.unlink(
            missing_ok=True,
        )

        shutil.rmtree(
            image_preview_dir.parent,
            ignore_errors=True,
        )
