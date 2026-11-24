from app.services.review_image_numbering import (
    assign_review_image_numbers,
    count_review_images,
)
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


def _review_chunk_key(
    document_id: str,
    chunk_index: int,
    job_id: str | None,
    claim_id: str | None,
) -> str:
    if job_id is None:
        return document_review_chunk_key(
            document_id,
            chunk_index,
        )

    if claim_id is None:
        return processing_review_chunk_key(
            document_id,
            job_id,
            chunk_index,
        )

    return processing_claim_review_chunk_key(
        document_id,
        job_id,
        claim_id,
        chunk_index,
    )


def _valid_review_pages(review_chunk: dict) -> list[dict]:
    return [
        page
        for page in review_chunk.get("pages", [])
        if isinstance(page, dict)
        and isinstance(page.get("pageNumber"), int)
    ]


def _has_unnumbered_images(pages: list[dict]) -> bool:
    return any(
        type(image.get("imageNumber")) is not int
        or image["imageNumber"] < 1
        for page in pages
        for image in page.get("images", [])
    )


def get_review_pages(
    *,
    document_id: str,
    page_start: int,
    page_end: int,
) -> list[dict]:
    """Load the requested pages with stable document-wide image numbers.

    Newly processed documents require only overlapping review chunks.

    For legacy chunks missing image numbers, count preceding images
    using manifest metadata where available, or read preceding review
    chunks as needed. Retain only counts, not preceding page contents.
    """
    pages: list[dict] = []
    chunks, job_id, claim_id = _get_manifest_chunks(document_id)

    image_counts: dict[int, int] = {}

    def load_chunk(chunk_index: int) -> list[dict]:
        chunk_key = _review_chunk_key(
            document_id,
            chunk_index,
            job_id,
            claim_id,
        )

        return _valid_review_pages(
            download_json_from_s3(chunk_key)
        )

    def count_chunk_images(chunk: dict) -> int:
        chunk_index = chunk.get("chunkIndex")

        if not isinstance(chunk_index, int):
            return 0

        if chunk_index in image_counts:
            return image_counts[chunk_index]

        manifest_count = chunk.get("imageCount")

        if (
            type(manifest_count) is int
            and manifest_count >= 0
        ):
            count = manifest_count
        else:
            count = count_review_images(
                load_chunk(chunk_index)
            )

        image_counts[chunk_index] = count

        return count

    for position, chunk in enumerate(chunks):
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

        chunk_pages = load_chunk(chunk_index)

        image_counts[chunk_index] = count_review_images(
            chunk_pages
        )

        if _has_unnumbered_images(chunk_pages):
            offset = chunk.get("imageNumberOffset")

            if type(offset) is not int or offset < 0:
                offset = sum(
                    count_chunk_images(previous)
                    for previous in chunks[:position]
                )

            assign_review_image_numbers(
                chunk_pages,
                previous_count=offset,
            )

        pages.extend(
            page
            for page in chunk_pages
            if page_start <= page["pageNumber"] <= page_end
        )

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
