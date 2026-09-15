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
