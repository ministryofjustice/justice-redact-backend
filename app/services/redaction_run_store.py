from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.document import Document
from app.models.redaction_decision import RedactionDecision
from app.models.redaction_run import RedactionRun


def redaction_run_to_dict(redaction_run: RedactionRun) -> dict:
    return {
        "runId": redaction_run.run_id,
        "documentId": redaction_run.document_id,
        "reviewRevision": redaction_run.review_revision,
        "status": redaction_run.status,
        "decisionsSnapshot": redaction_run.decisions_snapshot,
        "attemptCount": redaction_run.attempt_count,
        "claimId": redaction_run.claim_id,
        "leaseExpiresAt": (
            redaction_run.lease_expires_at.isoformat()
            if redaction_run.lease_expires_at
            else None
        ),
        "pageCounts": redaction_run.page_counts,
        "errorMessage": redaction_run.error_message,
        "createdAt": (
            redaction_run.created_at.isoformat() if redaction_run.created_at else None
        ),
        "startedAt": (
            redaction_run.started_at.isoformat() if redaction_run.started_at else None
        ),
        "completedAt": (
            redaction_run.completed_at.isoformat()
            if redaction_run.completed_at
            else None
        ),
        "cancelledAt": (
            redaction_run.cancelled_at.isoformat()
            if redaction_run.cancelled_at
            else None
        ),
    }


def get_redaction_run(run_id: str) -> dict | None:
    with SessionLocal() as session:
        redaction_run = session.get(
            RedactionRun,
            run_id,
        )

        if redaction_run is None:
            return None

        return redaction_run_to_dict(redaction_run)


def create_redaction_run(
    *,
    run_id: str,
    document_id: str,
    expected_review_revision: int,
) -> dict:
    now = datetime.now(timezone.utc)

    with SessionLocal() as session:
        document = session.execute(
            select(Document)
            .where(Document.document_id == document_id)
            .with_for_update()
        ).scalar_one_or_none()

        if document is None:
            return {
                "created": False,
                "reason": "document_not_found",
            }

        redaction_decision = session.execute(
            select(RedactionDecision)
            .where(RedactionDecision.document_id == document_id)
            .with_for_update()
        ).scalar_one_or_none()

        if redaction_decision is None:
            return {
                "created": False,
                "reason": "decisions_not_found",
                "currentRevision": 0,
            }

        if redaction_decision.revision != expected_review_revision:
            return {
                "created": False,
                "reason": "revision_conflict",
                "currentRevision": redaction_decision.revision,
            }

        previous_run_id = document.current_redaction_run_id

        if previous_run_id and previous_run_id != run_id:
            previous_run = session.execute(
                select(RedactionRun)
                .where(RedactionRun.run_id == previous_run_id)
                .with_for_update()
            ).scalar_one_or_none()

            if previous_run is not None and previous_run.status in {
                "enqueueing",
                "queued",
                "processing",
                "retrying",
            }:
                previous_run.status = "cancelled"
                previous_run.cancelled_at = now
                previous_run.claim_id = None
                previous_run.lease_expires_at = None

        redaction_run = RedactionRun(
            run_id=run_id,
            document_id=document_id,
            review_revision=redaction_decision.revision,
            status="enqueueing",
            decisions_snapshot=deepcopy(redaction_decision.decisions_json),
            attempt_count=0,
            claim_id=None,
            lease_expires_at=None,
            page_counts=None,
            error_message=None,
        )

        session.add(redaction_run)

        # Ensure the redaction run exists before documents.current_redaction_run_id
        # references it through the foreign key.
        session.flush()

        document.current_redaction_run_id = run_id
        document.status = "applying_redactions"
        document.redaction_started_at = now
        document.redaction_completed_at = None
        document.error_message = None

        session.commit()

        return {
            "created": True,
            "runId": run_id,
            "reviewRevision": redaction_decision.revision,
        }


def mark_redaction_run_queued(
    *,
    run_id: str,
) -> bool:
    now = datetime.now(timezone.utc)

    with SessionLocal() as session:
        existing_run = session.get(
            RedactionRun,
            run_id,
        )

        if existing_run is None:
            return False

        document = session.execute(
            select(Document)
            .where(Document.document_id == existing_run.document_id)
            .with_for_update()
        ).scalar_one_or_none()

        redaction_run = session.execute(
            select(RedactionRun).where(RedactionRun.run_id == run_id).with_for_update()
        ).scalar_one_or_none()

        if redaction_run is None:
            return False

        if document is None or document.current_redaction_run_id != run_id:
            if redaction_run.status == "enqueueing":
                redaction_run.status = "cancelled"
                redaction_run.cancelled_at = now
                redaction_run.claim_id = None
                redaction_run.lease_expires_at = None

                session.commit()

            return False

        if redaction_run.status == "enqueueing":
            redaction_run.status = "queued"
            session.commit()
            return True

        # SQS delivery can race ahead of the API request. If the current
        # authoritative run has already progressed beyond enqueueing,
        # enqueueing still succeeded and must not be reported as a
        # superseded run.
        if redaction_run.status in {
            "queued",
            "processing",
            "retrying",
            "completed",
            "failed",
        }:
            return True

        return False


def fail_redaction_run_enqueue(
    *,
    run_id: str,
    error_message: str,
) -> bool:
    now = datetime.now(timezone.utc)

    with SessionLocal() as session:
        existing_run = session.get(
            RedactionRun,
            run_id,
        )

        if existing_run is None:
            return False

        document = session.execute(
            select(Document)
            .where(Document.document_id == existing_run.document_id)
            .with_for_update()
        ).scalar_one_or_none()

        redaction_run = session.execute(
            select(RedactionRun).where(RedactionRun.run_id == run_id).with_for_update()
        ).scalar_one_or_none()

        if redaction_run is None:
            return False

        if redaction_run.status != "enqueueing":
            return False

        redaction_run.status = "failed"
        redaction_run.error_message = error_message
        redaction_run.completed_at = now
        redaction_run.claim_id = None
        redaction_run.lease_expires_at = None

        # Only roll the document back if this run still owns Apply
        # authority. A newer Apply run must never be overwritten by
        # the failure of an older request.
        if document is not None and document.current_redaction_run_id == run_id:
            document.current_redaction_run_id = None
            document.status = "ready_for_review"
            document.redaction_started_at = None
            document.redaction_completed_at = None
            document.error_message = None

        session.commit()

        return True


def claim_redaction_run(
    *,
    run_id: str,
    claim_id: str,
    attempt_count: int,
    lease_expires_at: datetime,
) -> bool:
    now = datetime.now(timezone.utc)

    with SessionLocal() as session:
        existing_run = session.get(
            RedactionRun,
            run_id,
        )

        if existing_run is None:
            return False

        # Always lock the document before the run. Other Redaction Run
        # transitions use the same lock order, avoiding competing workers
        # acquiring the rows in opposite order.
        document = session.execute(
            select(Document)
            .where(Document.document_id == existing_run.document_id)
            .with_for_update()
        ).scalar_one_or_none()

        redaction_run = session.execute(
            select(RedactionRun).where(RedactionRun.run_id == run_id).with_for_update()
        ).scalar_one_or_none()

        if document is None or redaction_run is None:
            return False

        # A stale or superseded run must never regain authority simply
        # because an old SQS message is delivered again.
        if document.current_redaction_run_id != run_id:
            return False

        if document.status != "applying_redactions":
            return False

        claimable = redaction_run.status in {
            "enqueueing",
            "queued",
            "retrying",
        }

        # SQS can redeliver a message if a worker dies. A processing run
        # may only be reclaimed after its database lease has expired.
        if redaction_run.status == "processing":
            claimable = (
                redaction_run.lease_expires_at is None
                or redaction_run.lease_expires_at <= now
            )

        if not claimable:
            return False

        redaction_run.status = "processing"
        redaction_run.claim_id = claim_id
        redaction_run.lease_expires_at = lease_expires_at
        redaction_run.attempt_count = attempt_count
        redaction_run.started_at = now
        redaction_run.completed_at = None
        redaction_run.error_message = None

        session.commit()

        return True


def is_redaction_run_owner(
    *,
    run_id: str,
    claim_id: str,
) -> bool:
    with SessionLocal() as session:
        redaction_run = session.get(
            RedactionRun,
            run_id,
        )

        if redaction_run is None:
            return False

        document = session.get(
            Document,
            redaction_run.document_id,
        )

        if document is None:
            return False

        return (
            redaction_run.status == "processing"
            and redaction_run.claim_id == claim_id
            and document.status == "applying_redactions"
            and document.current_redaction_run_id == run_id
        )


def renew_redaction_run_lease(
    *,
    run_id: str,
    claim_id: str,
    lease_expires_at: datetime,
) -> bool:
    with SessionLocal() as session:
        existing_run = session.get(
            RedactionRun,
            run_id,
        )

        if existing_run is None:
            return False

        document = session.execute(
            select(Document)
            .where(Document.document_id == existing_run.document_id)
            .with_for_update()
        ).scalar_one_or_none()

        redaction_run = session.execute(
            select(RedactionRun).where(RedactionRun.run_id == run_id).with_for_update()
        ).scalar_one_or_none()

        if document is None or redaction_run is None:
            return False

        if (
            document.status != "applying_redactions"
            or document.current_redaction_run_id != run_id
            or redaction_run.status != "processing"
            or redaction_run.claim_id != claim_id
        ):
            return False

        redaction_run.lease_expires_at = lease_expires_at

        session.commit()

        return True


def complete_redaction_run(
    *,
    run_id: str,
    claim_id: str,
    page_counts: dict | None = None,
) -> bool:
    now = datetime.now(timezone.utc)

    with SessionLocal() as session:
        existing_run = session.get(
            RedactionRun,
            run_id,
        )

        if existing_run is None:
            return False

        document = session.execute(
            select(Document)
            .where(Document.document_id == existing_run.document_id)
            .with_for_update()
        ).scalar_one_or_none()

        redaction_run = session.execute(
            select(RedactionRun).where(RedactionRun.run_id == run_id).with_for_update()
        ).scalar_one_or_none()

        if document is None or redaction_run is None:
            return False

        # Completion is authoritative only while this exact worker claim
        # still owns the document's current Apply Redactions run.
        if (
            document.status != "applying_redactions"
            or document.current_redaction_run_id != run_id
            or redaction_run.status != "processing"
            or redaction_run.claim_id != claim_id
        ):
            return False

        redaction_run.status = "completed"
        redaction_run.page_counts = deepcopy(page_counts)
        redaction_run.completed_at = now
        redaction_run.claim_id = None
        redaction_run.lease_expires_at = None
        redaction_run.error_message = None

        document.status = "redaction_complete"
        document.redaction_completed_at = now
        document.error_message = None

        session.commit()

        return True


def fail_redaction_run(
    *,
    run_id: str,
    claim_id: str,
    error_message: str,
    terminal: bool,
) -> bool:
    now = datetime.now(timezone.utc)

    with SessionLocal() as session:
        existing_run = session.get(
            RedactionRun,
            run_id,
        )

        if existing_run is None:
            return False

        document = session.execute(
            select(Document)
            .where(Document.document_id == existing_run.document_id)
            .with_for_update()
        ).scalar_one_or_none()

        redaction_run = session.execute(
            select(RedactionRun).where(RedactionRun.run_id == run_id).with_for_update()
        ).scalar_one_or_none()

        if document is None or redaction_run is None:
            return False

        # A failed stale worker must never alter the state belonging to
        # a newer Apply Redactions run.
        if (
            document.status != "applying_redactions"
            or document.current_redaction_run_id != run_id
            or redaction_run.status != "processing"
            or redaction_run.claim_id != claim_id
        ):
            return False

        redaction_run.status = "failed" if terminal else "retrying"
        redaction_run.error_message = error_message
        redaction_run.claim_id = None
        redaction_run.lease_expires_at = None

        if terminal:
            redaction_run.completed_at = now

            document.status = "redaction_failed"
            document.redaction_completed_at = now
            document.error_message = error_message
        else:
            redaction_run.completed_at = None

            # Keep the document on Applying Redactions while SQS retries.
            document.status = "applying_redactions"
            document.redaction_completed_at = None
            document.error_message = None

        session.commit()

        return True
