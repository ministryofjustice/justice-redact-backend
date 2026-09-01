import pytest

from app.services.workflow_service import resolve_workflow_navigation


@pytest.mark.parametrize(
    (
        "status",
        "warning_reason",
        "warning_acknowledged",
        "preferred_page",
        "allowed_pages",
    ),
    [
        (
            "uploaded",
            None,
            False,
            "subject-details",
            {"subject-details"},
        ),
        (
            "uploaded",
            "scanned",
            False,
            "document-warning",
            {"document-warning"},
        ),
        (
            "uploaded",
            "unsupported-document-type",
            False,
            "document-warning",
            {"document-warning"},
        ),
        (
            "uploaded",
            "scanned",
            True,
            "subject-details",
            {"subject-details"},
        ),
        (
            "enqueueing",
            None,
            False,
            "processing",
            {"processing"},
        ),
        (
            "queued",
            None,
            False,
            "processing",
            {"processing"},
        ),
        (
            "processing",
            None,
            False,
            "processing",
            {"processing"},
        ),
        (
            "retrying",
            None,
            False,
            "processing",
            {"processing"},
        ),
        (
            "ready_for_review",
            None,
            False,
            "review",
            {"review"},
        ),
        (
            "applying_redactions",
            None,
            False,
            "applying-redactions",
            {"applying-redactions"},
        ),
        (
            "redaction_complete",
            None,
            False,
            "export",
            {"review", "export"},
        ),
        (
            "abandoned",
            None,
            False,
            "upload",
            {"upload"},
        ),
    ],
)
def test_resolve_workflow_navigation(
    status,
    warning_reason,
    warning_acknowledged,
    preferred_page,
    allowed_pages,
):
    navigation = resolve_workflow_navigation(
        status=status,
        warning_reason=warning_reason,
        warning_acknowledged=warning_acknowledged,
    )

    assert navigation.preferred_page == preferred_page
    assert navigation.allowed_pages == frozenset(allowed_pages)


@pytest.mark.parametrize(
    ("status", "preferred_page"),
    [
        ("enqueue_failed", "subject-details"),
        ("failed", "processing"),
        ("redaction_failed", "applying-redactions"),
    ],
)
def test_failure_states_have_a_known_recovery_page(status, preferred_page):
    navigation = resolve_workflow_navigation(
        status=status,
        warning_reason=None,
        warning_acknowledged=False,
    )

    assert navigation.preferred_page == preferred_page
    assert preferred_page in navigation.allowed_pages


def test_unknown_status_is_rejected():
    with pytest.raises(ValueError, match="Unsupported document workflow status"):
        resolve_workflow_navigation(
            status="something_unknown",
            warning_reason=None,
            warning_acknowledged=False,
        )


def test_build_workflow_response_for_review_document():
    from app.services.workflow_service import build_workflow_response

    response = build_workflow_response(
        {
            "documentId": "document-123",
            "status": "ready_for_review",
            "warningReason": None,
            "warningAcknowledgedAt": None,
        }
    )

    assert response == {
        "documentId": "document-123",
        "status": "ready_for_review",
        "currentRedactionRunId": None,
        "preferredPage": "review",
        "allowedPages": ["review"],
    }


def test_build_workflow_response_for_unacknowledged_warning():
    from app.services.workflow_service import build_workflow_response

    response = build_workflow_response(
        {
            "documentId": "document-123",
            "status": "uploaded",
            "warningReason": "scanned",
            "warningAcknowledgedAt": None,
        }
    )

    assert response == {
        "documentId": "document-123",
        "status": "uploaded",
        "currentRedactionRunId": None,
        "preferredPage": "document-warning",
        "allowedPages": ["document-warning"],
    }


def test_build_workflow_response_treats_acknowledgement_timestamp_as_acknowledged():
    from app.services.workflow_service import build_workflow_response

    response = build_workflow_response(
        {
            "documentId": "document-123",
            "status": "uploaded",
            "warningReason": "scanned",
            "warningAcknowledgedAt": "2026-08-19T09:00:00+00:00",
        }
    )

    assert response == {
        "documentId": "document-123",
        "status": "uploaded",
        "currentRedactionRunId": None,
        "preferredPage": "subject-details",
        "allowedPages": ["subject-details"],
    }


def test_build_workflow_response_includes_current_redaction_run_id():
    from app.services.workflow_service import build_workflow_response

    response = build_workflow_response(
        {
            "documentId": "document-123",
            "status": "redaction_complete",
            "currentRedactionRunId": "run-456",
            "warningReason": None,
            "warningAcknowledgedAt": None,
        }
    )

    assert response == {
        "documentId": "document-123",
        "status": "redaction_complete",
        "currentRedactionRunId": "run-456",
        "preferredPage": "export",
        "allowedPages": ["review", "export"],
    }
