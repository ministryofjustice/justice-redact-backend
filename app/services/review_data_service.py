from app.services.s3_keys import (
    document_review_chunk_key,
    document_review_manifest_key,
    document_review_search_chunk_key,
)
from app.services.s3_service import download_json_from_s3


def _get_manifest_chunks(document_id: str) -> list[dict]:
    manifest = download_json_from_s3(document_review_manifest_key(document_id))

    chunks = manifest.get("chunks", [])

    if not isinstance(chunks, list):
        return []

    return sorted(
        chunks,
        key=lambda chunk: chunk.get("chunkIndex", 0),
    )


def get_review_pages(
    *,
    document_id: str,
    page_start: int,
    page_end: int,
) -> list[dict]:
    """
    Load only the review chunks that overlap the requested page range.

    Review chunks are stored in the frontend-ready ReviewPageData shape.
    """
    pages: list[dict] = []

    for chunk in _get_manifest_chunks(document_id):
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

        review_chunk = download_json_from_s3(
            document_review_chunk_key(
                document_id,
                chunk_index,
            )
        )

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
    Load the compact document-wide representation used by Find in document.

    These payloads contain source text and stable identifiers but omit the
    heavy rendering geometry, text spans and image data from review chunks.
    """
    pages: list[dict] = []

    for chunk in _get_manifest_chunks(document_id):
        chunk_index = chunk.get("chunkIndex")

        if not isinstance(chunk_index, int):
            continue

        search_chunk = download_json_from_s3(
            document_review_search_chunk_key(
                document_id,
                chunk_index,
            )
        )

        chunk_pages = search_chunk.get("pages", [])

        if isinstance(chunk_pages, list):
            pages.extend(chunk_pages)

    return sorted(
        pages,
        key=lambda page: page["pageNumber"],
    )
