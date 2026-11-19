from types import SimpleNamespace

import pytest

from app.services.redaction_service import (
    has_applied_content_redactions,
)
from app.services.redaction_run_store import (
    redaction_run_to_dict,
)


def decision(
    page=1,
    *,
    kind="text",
    action="redact",
    source="manual",
    resolved=True,
):
    item = SimpleNamespace(
        page_number=page,
        kind=kind,
        action=action,
        source=source,
    )
    return item, object() if resolved else None


@pytest.mark.parametrize(
    "kind",
    ["text", "table_cell", "image"],
)
def test_retained_content_redaction_is_reported(kind):
    assert has_applied_content_redactions(
        resolved_decisions=[decision(kind=kind)],
        excluded_page_numbers=[],
    ) is True


def test_redaction_on_exempted_page_not_counted():
    assert has_applied_content_redactions(
        resolved_decisions=[decision(page=2)],
        excluded_page_numbers=[2],
    ) is False


def test_redaction_on_deleted_page_not_counted():
    assert has_applied_content_redactions(
        resolved_decisions=[decision(page=3)],
        excluded_page_numbers=[3],
    ) is False


def test_unresolved_redaction_not_counted():
    assert has_applied_content_redactions(
        resolved_decisions=[
            decision(resolved=False),
        ],
        excluded_page_numbers=[],
    ) is False


@pytest.mark.parametrize(
    "action",
    ["suggest", "ignore", "disclose"],
)
def test_non_redaction_actions_not_counted(action):
    assert has_applied_content_redactions(
        resolved_decisions=[
            decision(action=action),
        ],
        excluded_page_numbers=[],
    ) is False


def test_unaccepted_ai_suggestion_not_counted():
    assert has_applied_content_redactions(
        resolved_decisions=[
            decision(source="ai"),
        ],
        excluded_page_numbers=[],
    ) is False


def test_empty_decisions_not_counted():
    assert has_applied_content_redactions(
        resolved_decisions=[],
        excluded_page_numbers=[],
    ) is False


def test_only_retained_applied_redaction_counts():
    assert has_applied_content_redactions(
        resolved_decisions=[
            decision(page=1),
            decision(page=2, resolved=False),
            decision(page=3, action="suggest"),
            decision(page=4, source="ai"),
            decision(page=5),
        ],
        excluded_page_numbers=[1, 5],
    ) is False

    assert has_applied_content_redactions(
        resolved_decisions=[
            decision(page=1),
            decision(page=2),
            decision(page=3, source="ai"),
        ],
        excluded_page_numbers=[1],
    ) is True


def make_redaction_run(page_counts):
    return SimpleNamespace(
        run_id="run-123",
        document_id="document-123",
        review_revision=3,
        status="completed",
        processing_progress=100,
        decisions_snapshot={},
        attempt_count=1,
        claim_id=None,
        lease_expires_at=None,
        page_counts=page_counts,
        error_message=None,
        created_at=None,
        started_at=None,
        completed_at=None,
        cancelled_at=None,
    )


BASE_COUNTS = {
    "original": 10,
    "exempt": 2,
    "deleted": 1,
    "redacted": 7,
}


@pytest.mark.parametrize("flag", [True, False])
def test_completed_run_exposes_content_redaction_flag(flag):
    stored_counts = {
        **BASE_COUNTS,
        "hasContentRedactions": flag,
    }

    result = redaction_run_to_dict(
        make_redaction_run(stored_counts)
    )

    assert result["hasContentRedactions"] is flag
    assert result["pageCounts"] == BASE_COUNTS


def test_legacy_run_does_not_invent_redaction_flag():
    result = redaction_run_to_dict(
        make_redaction_run(BASE_COUNTS.copy())
    )

    assert "hasContentRedactions" not in result
    assert result["pageCounts"] == BASE_COUNTS


def test_run_without_counts_remains_supported():
    result = redaction_run_to_dict(
        make_redaction_run(None)
    )

    assert result["pageCounts"] is None
    assert "hasContentRedactions" not in result
