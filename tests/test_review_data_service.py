from app.services import review_data_service


def test_get_review_pages_loads_only_overlapping_chunks(
    monkeypatch,
):
    reads = []

    # Legacy documents have no processingAssets metadata.
    # Never connect to a real database in these unit tests.
    monkeypatch.setattr(
        review_data_service,
        "get_review_result",
        lambda document_id: {"documentId": document_id},
    )

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

    # Legacy documents have no processingAssets metadata.
    # Never connect to a real database in these unit tests.
    monkeypatch.setattr(
        review_data_service,
        "get_review_result",
        lambda document_id: {"documentId": document_id},
    )

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

    # Legacy documents have no processingAssets metadata.
    # Never connect to a real database in these unit tests.
    monkeypatch.setattr(
        review_data_service,
        "get_review_result",
        lambda document_id: {"documentId": document_id},
    )

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


def test_review_data_uses_published_processing_job_assets(
    monkeypatch,
):
    document_id = "document-123"
    job_id = "job-456"

    monkeypatch.setattr(
        review_data_service,
        "get_review_result",
        lambda document_id: {
            "documentId": document_id,
            "processingAssets": {
                "layout": "job",
                "jobId": job_id,
            },
        },
    )

    prefix = (
        f"documents/{document_id}/"
        f"processing-jobs/{job_id}/review"
    )

    manifest_key = f"{prefix}/manifest.json"
    review_chunk_key = f"{prefix}/chunks/0000.json"
    search_chunk_key = f"{prefix}/search/0000.json"

    responses = {
        manifest_key: {
            "chunks": [
                {
                    "chunkIndex": 0,
                    "pageStart": 1,
                    "pageEnd": 10,
                },
            ],
        },
        review_chunk_key: {
            "pages": [
                {"pageNumber": 1},
                {"pageNumber": 2},
            ],
        },
        search_chunk_key: {
            "pages": [
                {
                    "pageNumber": 1,
                    "textItems": [],
                    "tables": [],
                    "images": [],
                },
            ],
        },
    }

    reads = []

    def fake_download_json_from_s3(key):
        reads.append(key)
        return responses[key]

    monkeypatch.setattr(
        review_data_service,
        "download_json_from_s3",
        fake_download_json_from_s3,
    )

    pages = review_data_service.get_review_pages(
        document_id=document_id,
        page_start=1,
        page_end=1,
    )

    assert [page["pageNumber"] for page in pages] == [1]

    search_pages = review_data_service.get_review_search_pages(
        document_id=document_id,
    )

    assert [page["pageNumber"] for page in search_pages] == [1]

    assert reads == [
        manifest_key,
        review_chunk_key,
        manifest_key,
        search_chunk_key,
    ]


def test_review_data_reads_only_published_claim_assets(monkeypatch):
    document_id = "document-123"
    job_id = "job-456"
    claim_id = "claim-winning"

    prefix = (
        f"documents/{document_id}/processing-jobs/{job_id}/"
        f"claims/{claim_id}/review"
    )

    monkeypatch.setattr(
        review_data_service,
        "get_review_result",
        lambda document_id: {
            "documentId": document_id,
            "processingAssets": {
                "layout": "claim",
                "jobId": job_id,
                "claimId": claim_id,
            },
        },
    )

    responses = {
        f"{prefix}/manifest.json": {
            "chunks": [
                {
                    "chunkIndex": 1,
                    "pageStart": 1,
                    "pageEnd": 100,
                },
            ],
        },
        f"{prefix}/chunks/0001.json": {
            "pages": [{"pageNumber": 1, "textItems": []}],
        },
        f"{prefix}/search/0001.json": {
            "pages": [{"pageNumber": 1, "textItems": []}],
        },
    }

    reads = []

    def fake_download(key):
        reads.append(key)
        return responses[key]

    monkeypatch.setattr(
        review_data_service,
        "download_json_from_s3",
        fake_download,
    )

    pages = review_data_service.get_review_pages(
        document_id=document_id,
        page_start=1,
        page_end=1,
    )

    search_pages = review_data_service.get_review_search_pages(
        document_id=document_id,
    )

    assert [page["pageNumber"] for page in pages] == [1]
    assert [page["pageNumber"] for page in search_pages] == [1]

    assert reads == [
        f"{prefix}/manifest.json",
        f"{prefix}/chunks/0001.json",
        f"{prefix}/manifest.json",
        f"{prefix}/search/0001.json",
    ]


def test_review_data_rejects_incomplete_claim_metadata(monkeypatch):
    import pytest

    monkeypatch.setattr(
        review_data_service,
        "get_review_result",
        lambda document_id: {
            "documentId": document_id,
            "processingAssets": {
                "layout": "claim",
                "jobId": "job-456",
                # Missing claimId must not trigger legacy fallback.
            },
        },
    )

    def unexpected_download(key):
        pytest.fail(f"Unexpected S3 read: {key}")

    monkeypatch.setattr(
        review_data_service,
        "download_json_from_s3",
        unexpected_download,
    )

    with pytest.raises(
        ValueError,
        match="Invalid processing asset storage metadata",
    ):
        review_data_service.get_review_pages(
            document_id="document-123",
            page_start=1,
            page_end=10,
        )
