from copy import deepcopy

from app.services import review_data_service
from app.services.review_image_numbering import (
    assign_review_image_numbers,
    count_review_images,
)


def make_image(image_id, *, number=None, bbox=None):
    image = {
        "imageId": image_id,
        "imageUrl": None,
        "bbox": bbox,
    }

    if number is not None:
        image["imageNumber"] = number

    return image


def make_page(page_number, images):
    return {
        "pageNumber": page_number,
        "images": images,
        "textItems": [],
        "tables": [],
    }


def image_numbers(pages):
    return [
        image["imageNumber"]
        for page in pages
        for image in page["images"]
    ]


def test_numbering_continues_across_processing_chunks():
    first_chunk = [
        make_page(1, [make_image("p1-i1")]),
        make_page(2, []),
        make_page(
            3,
            [
                make_image("p3-i1"),
                make_image("p3-i2"),
            ],
        ),
    ]

    second_chunk = [
        make_page(4, [make_image("p4-i1")]),
        make_page(5, [make_image("p5-i1")]),
    ]

    count = assign_review_image_numbers(first_chunk)

    assert count == 3
    assert image_numbers(first_chunk) == [1, 2, 3]

    count = assign_review_image_numbers(
        second_chunk,
        previous_count=count,
    )

    assert count == 5
    assert image_numbers(second_chunk) == [4, 5]


def test_numbering_preserves_extraction_order_within_pages():
    pages = [
        make_page(
            2,
            [
                make_image("p2-i2"),
                make_image("p2-i1"),
            ],
        ),
        make_page(1, [make_image("p1-i1")]),
    ]

    count = assign_review_image_numbers(pages)

    assert count == 3

    # The page list is not reordered as a side effect.
    assert pages[0]["pageNumber"] == 2

    # Numbering follows page order, then extraction order.
    assert image_numbers(pages) == [2, 3, 1]


def test_images_without_preview_geometry_are_numbered():
    pages = [
        make_page(
            1,
            [
                make_image("missing-preview"),
                make_image(
                    "valid-preview",
                    bbox={
                        "x0": 0,
                        "y0": 0,
                        "x1": 100,
                        "y1": 100,
                    },
                ),
            ],
        ),
    ]

    original = deepcopy(pages)

    assert assign_review_image_numbers(pages) == 2
    assert count_review_images(pages) == 2
    assert image_numbers(pages) == [1, 2]

    # Numbering must not alter identifiers or PDF geometry.
    for image, previous in zip(
        pages[0]["images"],
        original[0]["images"],
    ):
        assert {
            key: value
            for key, value in image.items()
            if key != "imageNumber"
        } == previous


def setup_review_chunks(monkeypatch, *, numbered):
    document_id = "document-123"

    chunks = [
        {
            "chunkIndex": 1,
            "pageStart": 1,
            "pageEnd": 2,
        },
        {
            "chunkIndex": 2,
            "pageStart": 3,
            "pageEnd": 4,
        },
        {
            "chunkIndex": 3,
            "pageStart": 5,
            "pageEnd": 6,
        },
    ]

    first = [
        make_page(
            1,
            [make_image("p1-i1"), make_image("p1-i2")],
        ),
        make_page(2, []),
    ]

    second = [
        make_page(3, [make_image("p3-i1")]),
        make_page(4, [make_image("p4-i1")]),
    ]

    third = [
        make_page(5, []),
        make_page(6, [make_image("p6-i1")]),
    ]

    all_pages = [first, second, third]

    if numbered:
        count = 0

        for chunk, pages in zip(chunks, all_pages):
            chunk["imageNumberOffset"] = count

            count = assign_review_image_numbers(
                pages,
                previous_count=count,
            )

            chunk["imageCount"] = (
                count - chunk["imageNumberOffset"]
            )

    job_id = "job-123"
    claim_id = "claim-123"

    monkeypatch.setattr(
        review_data_service,
        "_get_manifest_chunks",
        lambda document_id: (
            chunks,
            job_id,
            claim_id,
        ),
    )

    keys = [
        review_data_service.processing_claim_review_chunk_key(
            document_id,
            job_id,
            claim_id,
            chunk["chunkIndex"],
        )
        for chunk in chunks
    ]

    stored = {
        key: {"pages": pages}
        for key, pages in zip(keys, all_pages)
    }

    reads = []

    def download(key):
        reads.append(key)
        return deepcopy(stored[key])

    monkeypatch.setattr(
        review_data_service,
        "download_json_from_s3",
        download,
    )

    return document_id, keys, reads, stored


def test_numbered_review_loads_only_overlapping_chunk(monkeypatch):
    document_id, keys, reads, _ = setup_review_chunks(
        monkeypatch,
        numbered=True,
    )

    pages = review_data_service.get_review_pages(
        document_id=document_id,
        page_start=4,
        page_end=4,
    )

    assert image_numbers(pages) == [4]
    assert reads == [keys[1]]


def test_legacy_review_recovers_numbers_from_preceding_chunks(
    monkeypatch,
):
    document_id, keys, reads, stored = setup_review_chunks(
        monkeypatch,
        numbered=False,
    )

    original = deepcopy(stored)

    pages = review_data_service.get_review_pages(
        document_id=document_id,
        page_start=4,
        page_end=4,
    )

    assert image_numbers(pages) == [4]
    assert reads == [keys[1], keys[0]]

    # The persisted historical review assets are not rewritten.
    assert stored == original


def test_legacy_range_does_not_reread_preceding_chunks(monkeypatch):
    document_id, keys, reads, _ = setup_review_chunks(
        monkeypatch,
        numbered=False,
    )

    pages = review_data_service.get_review_pages(
        document_id=document_id,
        page_start=3,
        page_end=6,
    )

    assert image_numbers(pages) == [3, 4, 5]
    assert reads == [keys[1], keys[0], keys[2]]
