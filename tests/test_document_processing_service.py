import pytest

from app.services import document_processing_service


def test_assert_processing_active_allows_current_processing_owner():
    document_processing_service.assert_processing_active(
        lambda: True,
    )


def test_assert_processing_active_raises_when_processing_is_no_longer_owned():
    with pytest.raises(
        document_processing_service.DocumentProcessingCancelled
    ):
        document_processing_service.assert_processing_active(
            lambda: False,
        )
