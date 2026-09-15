from app.services import review_data_service


def test_get_review_pages_loads_only_overlapping_chunks(
    monkeypatch,
):
    reads = []

    manifest_key = "documents/document-123/review/manifest.json"

    responses = {
        manifest_key: {
            "chunkSize": 100,
            "totalPages": 300,
            "chunks": [
                {
                    "chunkIndex": 1,
                    "pageStart": 1,
                    "pageEnd": 100,
                },
                {
                    "chunkIndex": 2,
                    "pageStart": 101,
                    "pageEnd": 200,
                },
                {
                    "chunkIndex": 3,
                    "pageStart": 201,
                    "pageEnd": 300,
                },
            ],
        },
        "documents/document-123/review/chunks/0001.json": {
            "pages": [
                {"pageNumber": 75},
                {"pageNumber": 76},
                {"pageNumber": 100},
            ],
        },
        "documents/document-123/review/chunks/0002.json": {
            "pages": [
                {"pageNumber": 101},
                {"pageNumber": 125},
                {"pageNumber": 126},
            ],
        },
    }

    def fake_download_json_from_s3(key):
        reads.append(key)
        return responses[key]

    monkeypatch.setattr(
        review_data_service,
        "download_json_from_s3",
        fake_download_json_from_s3,
    )

    pages = review_data_service.get_review_pages(
        document_id="document-123",
        page_start=76,
        page_end=125,
    )

    assert pages == [
        {"pageNumber": 76},
        {"pageNumber": 100},
        {"pageNumber": 101},
        {"pageNumber": 125},
    ]

    assert reads == [
        "documents/document-123/review/manifest.json",
        "documents/document-123/review/chunks/0001.json",
        "documents/document-123/review/chunks/0002.json",
    ]


def test_get_review_pages_loads_single_storage_chunk_when_possible(
    monkeypatch,
):
    reads = []

    responses = {
        "documents/document-123/review/manifest.json": {
            "chunkSize": 100,
            "totalPages": 200,
            "chunks": [
                {
                    "chunkIndex": 1,
                    "pageStart": 1,
                    "pageEnd": 100,
                },
                {
                    "chunkIndex": 2,
                    "pageStart": 101,
                    "pageEnd": 200,
                },
            ],
        },
        "documents/document-123/review/chunks/0001.json": {
            "pages": [
                {"pageNumber": 1},
                {"pageNumber": 50},
                {"pageNumber": 51},
            ],
        },
    }

    def fake_download_json_from_s3(key):
        reads.append(key)
        return responses[key]

    monkeypatch.setattr(
        review_data_service,
        "download_json_from_s3",
        fake_download_json_from_s3,
    )

    pages = review_data_service.get_review_pages(
        document_id="document-123",
        page_start=1,
        page_end=50,
    )

    assert pages == [
        {"pageNumber": 1},
        {"pageNumber": 50},
    ]

    assert reads == [
        "documents/document-123/review/manifest.json",
        "documents/document-123/review/chunks/0001.json",
    ]


def test_get_review_search_pages_combines_chunks_in_page_order(
    monkeypatch,
):
    reads = []

    responses = {
        "documents/document-123/review/manifest.json": {
            "chunkSize": 100,
            "totalPages": 200,
            "chunks": [
                {
                    "chunkIndex": 2,
                    "pageStart": 101,
                    "pageEnd": 200,
                },
                {
                    "chunkIndex": 1,
                    "pageStart": 1,
                    "pageEnd": 100,
                },
            ],
        },
        "documents/document-123/review/search/0001.json": {
            "pages": [
                {
                    "pageNumber": 1,
                    "textItems": [
                        {
                            "itemId": "item-1",
                            "text": "first page",
                        }
                    ],
                    "tables": [],
                    "images": [],
                }
            ],
        },
        "documents/document-123/review/search/0002.json": {
            "pages": [
                {
                    "pageNumber": 101,
                    "textItems": [
                        {
                            "itemId": "item-101",
                            "text": "later page",
                        }
                    ],
                    "tables": [],
                    "images": [],
                }
            ],
        },
    }

    def fake_download_json_from_s3(key):
        reads.append(key)
        return responses[key]

    monkeypatch.setattr(
        review_data_service,
        "download_json_from_s3",
        fake_download_json_from_s3,
    )

    pages = review_data_service.get_review_search_pages(
        document_id="document-123",
    )

    assert [page["pageNumber"] for page in pages] == [1, 101]

    assert reads == [
        "documents/document-123/review/manifest.json",
        "documents/document-123/review/search/0001.json",
        "documents/document-123/review/search/0002.json",
    ]
