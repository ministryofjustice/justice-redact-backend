import pytest

from app.services import document_processing_service


def test_assert_processing_active_allows_current_processing_owner():
    document_processing_service.assert_processing_active(
        lambda: True,
    )


def test_assert_processing_active_raises_when_processing_is_no_longer_owned():
    with pytest.raises(document_processing_service.DocumentProcessingCancelled):
        document_processing_service.assert_processing_active(
            lambda: False,
        )


def test_build_review_search_pages_keeps_only_searchable_text_data():
    review_pages = [
        {
            "pageNumber": 7,
            "pageId": "page-7",
            "textItems": [
                {
                    "itemId": "item-1",
                    "text": "John Smith",
                    "renderText": "John Smith",
                    "bbox": {
                        "x0": 10,
                        "y0": 20,
                        "x1": 30,
                        "y1": 40,
                    },
                    "style": {
                        "is_bold": True,
                    },
                    "textSpans": [
                        {
                            "text": "John Smith",
                            "start": 0,
                            "end": 10,
                        }
                    ],
                }
            ],
            "tables": [],
            "images": [
                {
                    "imageId": "image-1",
                    "imageUrl": "/example.png",
                }
            ],
        }
    ]

    result = document_processing_service.build_review_search_pages(review_pages)

    assert result == [
        {
            "pageNumber": 7,
            "pageId": "page-7",
            "textItems": [
                {
                    "itemId": "item-1",
                    "text": "John Smith",
                    "renderText": "John Smith",
                    "bbox": None,
                }
            ],
            "tables": [],
            "images": [],
        }
    ]


def test_build_review_search_pages_preserves_table_cell_identity_and_text():
    review_pages = [
        {
            "pageNumber": 12,
            "pageId": "page-12",
            "textItems": [],
            "tables": [
                {
                    "tableId": "table-1",
                    "bbox": {
                        "x0": 1,
                        "y0": 2,
                        "x1": 3,
                        "y1": 4,
                    },
                    "rows": [
                        {
                            "rowIndex": 2,
                            "cells": [
                                {
                                    "cellId": "cell-1",
                                    "tableId": "table-1",
                                    "rowIndex": 2,
                                    "colIndex": 3,
                                    "text": "ABC123",
                                    "renderText": "ABC123",
                                    "bbox": {
                                        "x0": 10,
                                        "y0": 20,
                                        "x1": 30,
                                        "y1": 40,
                                    },
                                    "isHeader": False,
                                    "isNumeric": False,
                                    "textSpans": [
                                        {
                                            "text": "ABC123",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
            "images": [],
        }
    ]

    result = document_processing_service.build_review_search_pages(review_pages)

    assert result == [
        {
            "pageNumber": 12,
            "pageId": "page-12",
            "textItems": [],
            "tables": [
                {
                    "tableId": "table-1",
                    "bbox": None,
                    "rows": [
                        {
                            "rowIndex": 2,
                            "cells": [
                                {
                                    "cellId": "cell-1",
                                    "tableId": "table-1",
                                    "rowIndex": 2,
                                    "colIndex": 3,
                                    "text": "ABC123",
                                    "renderText": "ABC123",
                                    "bbox": None,
                                    "isHeader": False,
                                    "isNumeric": False,
                                }
                            ],
                        }
                    ],
                }
            ],
            "images": [],
        }
    ]


def test_log_memory_snapshot_reads_cgroup_and_process_memory(
    tmp_path,
    monkeypatch,
):
    memory_current = tmp_path / "memory.current"
    memory_peak = tmp_path / "memory.peak"
    memory_max = tmp_path / "memory.max"
    memory_stat = tmp_path / "memory.stat"
    process_status = tmp_path / "status"

    memory_current.write_text(str(512 * 1024 * 1024))
    memory_peak.write_text(str(768 * 1024 * 1024))
    memory_max.write_text(str(2 * 1024 * 1024 * 1024))

    memory_stat.write_text(
        "\n".join(
            [
                f"anon {400 * 1024 * 1024}",
                f"file {90 * 1024 * 1024}",
                f"kernel {20 * 1024 * 1024}",
            ]
        )
    )

    process_status.write_text(
        "\n".join(
            [
                "Name:\tpython",
                "VmRSS:\t307200 kB",
                "RssAnon:\t266240 kB",
                "RssFile:\t40960 kB",
                "RssShmem:\t0 kB",
            ]
        )
    )

    monkeypatch.setattr(
        document_processing_service,
        "_CGROUP_MEMORY_CURRENT_PATH",
        memory_current,
    )
    monkeypatch.setattr(
        document_processing_service,
        "_CGROUP_MEMORY_PEAK_PATH",
        memory_peak,
    )
    monkeypatch.setattr(
        document_processing_service,
        "_CGROUP_MEMORY_MAX_PATH",
        memory_max,
    )
    monkeypatch.setattr(
        document_processing_service,
        "_CGROUP_MEMORY_STAT_PATH",
        memory_stat,
    )
    monkeypatch.setattr(
        document_processing_service,
        "_PROC_SELF_STATUS_PATH",
        process_status,
    )

    log_calls = []

    def fake_logger_info(message, *, extra):
        log_calls.append(
            {
                "message": message,
                "extra": extra,
            }
        )

    monkeypatch.setattr(
        document_processing_service.logger,
        "info",
        fake_logger_info,
    )

    document_processing_service._log_memory_snapshot(
        point="after_detection",
        document_id="document-123",
        chunk_index=4,
        chunk_count=78,
        combined_findings_count=25,
        analyser_cache_size=2,
        postprocessor_cache_size=3,
    )

    assert len(log_calls) == 1

    logged = log_calls[0]

    assert logged["message"] == "document_processing_memory"

    extra = logged["extra"]

    assert extra["event"] == "document_processing_memory"
    assert extra["point"] == "after_detection"
    assert extra["document_id"] == "document-123"
    assert extra["chunk_index"] == 4
    assert extra["chunk_count"] == 78

    assert extra["memory_current_mb"] == 512.0
    assert extra["memory_peak_mb"] == 768.0
    assert extra["memory_limit_mb"] == 2048.0

    assert extra["memory_anon_mb"] == 400.0
    assert extra["memory_file_mb"] == 90.0
    assert extra["memory_kernel_mb"] == 20.0

    assert extra["process_rss_mb"] == 300.0
    assert extra["process_rss_anon_mb"] == 260.0
    assert extra["process_rss_file_mb"] == 40.0
    assert extra["process_rss_shmem_mb"] == 0.0

    assert extra["combined_findings_count"] == 25
    assert extra["analyser_cache_size"] == 2
    assert extra["postprocessor_cache_size"] == 3


def test_memory_snapshot_handles_unavailable_memory_files(
    tmp_path,
    monkeypatch,
):
    missing_path = tmp_path / "does-not-exist"

    monkeypatch.setattr(
        document_processing_service,
        "_CGROUP_MEMORY_CURRENT_PATH",
        missing_path,
    )
    monkeypatch.setattr(
        document_processing_service,
        "_CGROUP_MEMORY_PEAK_PATH",
        missing_path,
    )
    monkeypatch.setattr(
        document_processing_service,
        "_CGROUP_MEMORY_MAX_PATH",
        missing_path,
    )
    monkeypatch.setattr(
        document_processing_service,
        "_CGROUP_MEMORY_STAT_PATH",
        missing_path,
    )
    monkeypatch.setattr(
        document_processing_service,
        "_PROC_SELF_STATUS_PATH",
        missing_path,
    )

    log_calls = []

    def fake_logger_info(message, *, extra):
        log_calls.append(
            {
                "message": message,
                "extra": extra,
            }
        )

    monkeypatch.setattr(
        document_processing_service.logger,
        "info",
        fake_logger_info,
    )

    document_processing_service._log_memory_snapshot(
        point="before_chunk",
        document_id="document-123",
        chunk_index=1,
        chunk_count=78,
        combined_findings_count=0,
        analyser_cache_size=0,
        postprocessor_cache_size=0,
    )

    assert len(log_calls) == 1

    extra = log_calls[0]["extra"]

    assert extra["memory_current_mb"] is None
    assert extra["memory_peak_mb"] is None
    assert extra["memory_limit_mb"] is None
    assert extra["memory_anon_mb"] is None
    assert extra["memory_file_mb"] is None
    assert extra["memory_kernel_mb"] is None
    assert extra["process_rss_mb"] is None
    assert extra["process_rss_anon_mb"] is None
    assert extra["process_rss_file_mb"] is None
    assert extra["process_rss_shmem_mb"] is None


def test_calculate_chunk_processing_progress_maps_single_chunk_stages():
    calculate = document_processing_service.calculate_chunk_processing_progress

    assert (
        calculate(
            total_pages=100,
            page_start=1,
            page_end=100,
            stage="extraction",
            completed=100,
            total=100,
        )
        == 33
    )

    assert (
        calculate(
            total_pages=100,
            page_start=1,
            page_end=100,
            stage="detection",
            completed=1,
            total=1,
        )
        == 65
    )

    assert (
        calculate(
            total_pages=100,
            page_start=1,
            page_end=100,
            stage="persistence",
            completed=1,
            total=4,
        )
        == 73
    )

    assert (
        calculate(
            total_pages=100,
            page_start=1,
            page_end=100,
            stage="persistence",
            completed=2,
            total=4,
        )
        == 81
    )

    assert (
        calculate(
            total_pages=100,
            page_start=1,
            page_end=100,
            stage="persistence",
            completed=3,
            total=4,
        )
        == 89
    )

    assert (
        calculate(
            total_pages=100,
            page_start=1,
            page_end=100,
            stage="persistence",
            completed=4,
            total=4,
        )
        == 98
    )


def test_calculate_chunk_processing_progress_weights_chunks_by_page_count():
    calculate = document_processing_service.calculate_chunk_processing_progress

    assert (
        calculate(
            total_pages=150,
            page_start=1,
            page_end=100,
            stage="persistence",
            completed=4,
            total=4,
        )
        == 65
    )

    assert (
        calculate(
            total_pages=150,
            page_start=101,
            page_end=150,
            stage="extraction",
            completed=50,
            total=50,
        )
        == 76
    )

    assert (
        calculate(
            total_pages=150,
            page_start=101,
            page_end=150,
            stage="persistence",
            completed=4,
            total=4,
        )
        == 98
    )


@pytest.mark.parametrize(
    "stage",
    [
        "unknown",
        "",
    ],
)
def test_calculate_chunk_processing_progress_rejects_unknown_stage(
    stage,
):
    with pytest.raises(
        ValueError,
        match="Unknown processing progress stage",
    ):
        document_processing_service.calculate_chunk_processing_progress(
            total_pages=100,
            page_start=1,
            page_end=100,
            stage=stage,
            completed=1,
            total=1,
        )


def test_processing_progress_reporter_only_persists_forward_progress(
    monkeypatch,
):
    updates = []

    def fake_update_document_processing_progress(**kwargs):
        updates.append(kwargs)
        return True

    monkeypatch.setattr(
        document_processing_service,
        "update_document_processing_progress",
        fake_update_document_processing_progress,
    )

    reporter = document_processing_service.DocumentProcessingProgressReporter(
        document_id="document-123",
        job_id="job-123",
        claim_id="claim-123",
        initial_progress=40,
    )

    reporter.report(40)
    reporter.report(35)
    reporter.report(41)
    reporter.report(41)
    reporter.report(45)

    assert updates == [
        {
            "document_id": "document-123",
            "job_id": "job-123",
            "claim_id": "claim-123",
            "progress": 41,
        },
        {
            "document_id": "document-123",
            "job_id": "job-123",
            "claim_id": "claim-123",
            "progress": 45,
        },
    ]

    assert reporter.last_persisted_progress == 45


def test_processing_progress_reporter_cancels_when_ownership_is_lost(
    monkeypatch,
):
    monkeypatch.setattr(
        document_processing_service,
        "update_document_processing_progress",
        lambda **kwargs: False,
    )

    reporter = document_processing_service.DocumentProcessingProgressReporter(
        document_id="document-123",
        job_id="job-123",
        claim_id="claim-123",
        initial_progress=20,
    )

    with pytest.raises(
        document_processing_service.DocumentProcessingCancelled,
        match="lost ownership",
    ):
        reporter.report(21)

    assert reporter.last_persisted_progress == 20


@pytest.mark.parametrize(
    "progress",
    [
        -1,
        100,
    ],
)
def test_processing_progress_reporter_rejects_invalid_progress(
    monkeypatch,
    progress,
):
    reporter = document_processing_service.DocumentProcessingProgressReporter(
        document_id="document-123",
        job_id="job-123",
        claim_id="claim-123",
        initial_progress=0,
    )

    with pytest.raises(
        ValueError,
        match="Processing progress must be between 0 and 99",
    ):
        reporter.report(progress)
