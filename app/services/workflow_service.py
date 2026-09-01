from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowNavigation:
    preferred_page: str
    allowed_pages: frozenset[str]


def resolve_workflow_navigation(
    *,
    status: str,
    warning_reason: str | None,
    warning_acknowledged: bool,
) -> WorkflowNavigation:
    if status == "uploaded":
        if warning_reason and not warning_acknowledged:
            return WorkflowNavigation(
                preferred_page="document-warning",
                allowed_pages=frozenset({"document-warning"}),
            )

        return WorkflowNavigation(
            preferred_page="subject-details",
            allowed_pages=frozenset({"subject-details"}),
        )

    if status == "enqueue_failed":
        return WorkflowNavigation(
            preferred_page="subject-details",
            allowed_pages=frozenset({"subject-details"}),
        )

    if status in {
        "enqueueing",
        "queued",
        "processing",
        "retrying",
        "failed",
    }:
        return WorkflowNavigation(
            preferred_page="processing",
            allowed_pages=frozenset({"processing"}),
        )

    if status == "ready_for_review":
        return WorkflowNavigation(
            preferred_page="review",
            allowed_pages=frozenset({"review"}),
        )

    if status in {
        "applying_redactions",
        "redaction_failed",
    }:
        return WorkflowNavigation(
            preferred_page="applying-redactions",
            allowed_pages=frozenset({"applying-redactions"}),
        )

    if status == "redaction_complete":
        return WorkflowNavigation(
            preferred_page="export",
            allowed_pages=frozenset({"review", "export"}),
        )

    if status == "abandoned":
        return WorkflowNavigation(
            preferred_page="upload",
            allowed_pages=frozenset({"upload"}),
        )

    raise ValueError(f"Unsupported document workflow status: {status}")


WORKFLOW_PAGE_ORDER = (
    "upload",
    "document-warning",
    "subject-details",
    "processing",
    "review",
    "applying-redactions",
    "export",
)


def build_workflow_response(document: dict) -> dict:
    navigation = resolve_workflow_navigation(
        status=document["status"],
        warning_reason=document.get("warningReason"),
        warning_acknowledged=bool(document.get("warningAcknowledgedAt")),
    )

    allowed_pages = [
        page for page in WORKFLOW_PAGE_ORDER if page in navigation.allowed_pages
    ]

    return {
        "documentId": document["documentId"],
        "status": document["status"],
        "currentRedactionRunId": document.get("currentRedactionRunId"),
        "preferredPage": navigation.preferred_page,
        "allowedPages": allowed_pages,
    }
