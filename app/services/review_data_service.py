from app.services.review_result_store import get_review_result
from app.services.s3_keys import (
    document_review_chunk_key,
    document_review_manifest_key,
    document_review_search_chunk_key,
    processing_review_chunk_key,
    processing_review_manifest_key,
    processing_review_search_chunk_key,
    processing_claim_review_manifest_key,
    processing_claim_review_chunk_key,
    processing_claim_review_search_chunk_key,
)
from app.services.s3_service import download_json_from_s3


def _get_manifest_chunks(
    document_id: str,
) -> tuple[list[dict], str | None, str | None]:
    review_result = get_review_result(document_id)

    if review_result is None:
        raise LookupError(
            f"Review result not found for document {document_id}"
        )

    assets = review_result.get("processingAssets")
    job_id: str | None = None
    claim_id: str | None = None

    if assets is None:
        # Legacy document-level storage.
        pass
    elif (
        isinstance(assets, dict)
        and assets.get("layout") == "job"
        and isinstance(assets.get("jobId"), str)
        and assets["jobId"]
    ):
        job_id = assets["jobId"]
    elif (
        isinstance(assets, dict)
        and assets.get("layout") == "claim"
        and isinstance(assets.get("jobId"), str)
        and assets["jobId"]
        and isinstance(assets.get("claimId"), str)
        and assets["claimId"]
    ):
        job_id = assets["jobId"]
        claim_id = assets["claimId"]
    else:
        raise ValueError(
            "Invalid processing asset storage metadata"
        )

    if job_id is None:
        manifest_key = document_review_manifest_key(
            document_id
        )
    elif claim_id is None:
        manifest_key = processing_review_manifest_key(
            document_id,
            job_id,
        )
    else:
        manifest_key = processing_claim_review_manifest_key(
            document_id,
            job_id,
            claim_id,
        )

    manifest = download_json_from_s3(manifest_key)
    chunks = manifest.get("chunks", [])

    if not isinstance(chunks, list):
        return [], job_id, claim_id

    return (
        sorted(
            chunks,
            key=lambda chunk: chunk.get("chunkIndex", 0),
        ),
        job_id,
        claim_id,
    )


def get_review_pages(
    *,
    document_id: str,
    page_start: int,
    page_end: int,
) -> list[dict]:
    """
    Load only review chunks overlapping the requested page range.
    """
    pages: list[dict] = []
    chunks, job_id, claim_id = _get_manifest_chunks(document_id)

    for chunk in chunks:
        chunk_index = chunk.get("chunkIndex")
        chunk_page_start = chunk.get("pageStart")
        chunk_page_end = chunk.get("pageEnd")

        if not isinstance(chunk_index, int):
            continue

        if not isinstance(chunk_page_start, int):
            continue

        if not isinstance(chunk_page_end, int):
            continue

        if chunk_page_end < page_start:
            continue

        if chunk_page_start > page_end:
            continue

        if job_id is None:
            chunk_key = document_review_chunk_key(
                document_id,
                chunk_index,
            )
        elif claim_id is None:
            chunk_key = processing_review_chunk_key(
                document_id,
                job_id,
                chunk_index,
            )
        else:
            chunk_key = processing_claim_review_chunk_key(
                document_id,
                job_id,
                claim_id,
                chunk_index,
            )

        review_chunk = download_json_from_s3(chunk_key)

        for page in review_chunk.get("pages", []):
            page_number = page.get("pageNumber")

            if not isinstance(page_number, int):
                continue

            if page_start <= page_number <= page_end:
                pages.append(page)

    return sorted(
        pages,
        key=lambda page: page["pageNumber"],
    )


def get_review_search_pages(
    *,
    document_id: str,
) -> list[dict]:
    """
    Load compact document-wide data used by Find in document.
    """
    pages: list[dict] = []
    chunks, job_id, claim_id = _get_manifest_chunks(document_id)

    for chunk in chunks:
        chunk_index = chunk.get("chunkIndex")

        if not isinstance(chunk_index, int):
            continue

        if job_id is None:
            chunk_key = document_review_search_chunk_key(
                document_id,
                chunk_index,
            )
        elif claim_id is None:
            chunk_key = processing_review_search_chunk_key(
                document_id,
                job_id,
                chunk_index,
            )
        else:
            chunk_key = processing_claim_review_search_chunk_key(
                document_id,
                job_id,
                claim_id,
                chunk_index,
            )

        search_chunk = download_json_from_s3(chunk_key)
        chunk_pages = search_chunk.get("pages", [])

        if isinstance(chunk_pages, list):
            pages.extend(chunk_pages)

    return sorted(
        pages,
        key=lambda page: page["pageNumber"],
    )
