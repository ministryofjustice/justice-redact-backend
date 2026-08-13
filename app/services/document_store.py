from fastapi import HTTPException
from datetime import datetime, timezone
from sqlalchemy import and_, or_, update

from app.core.database import SessionLocal
from app.models.document import Document


def document_to_dict(document: Document) -> dict:
    return {
        "documentId": document.document_id,
        "filename": document.filename,
        "status": document.status,
        "documentType": document.document_type,
        "processingJobId": document.processing_job_id,
        "processingAttemptCount": document.processing_attempt_count,
        "processingClaimId": document.processing_claim_id,
        "processingLeaseExpiresAt": (
            document.processing_lease_expires_at.isoformat()
            if document.processing_lease_expires_at
            else None
        ),
        "subjectName": document.subject_name,
        "subjectPrisonNumber": document.subject_prison_number,
        "otherPhrases": document.other_phrases,
        "createdAt": document.created_at.isoformat() if document.created_at else None,
        "updatedAt": document.updated_at.isoformat() if document.updated_at else None,
        "processingStartedAt": (
            document.processing_started_at.isoformat()
            if document.processing_started_at
            else None
        ),
        "processingCompletedAt": (
            document.processing_completed_at.isoformat()
            if document.processing_completed_at
            else None
        ),
        "redactionStartedAt": (
            document.redaction_started_at.isoformat()
            if document.redaction_started_at
            else None
        ),
        "redactionCompletedAt": (
            document.redaction_completed_at.isoformat()
            if document.redaction_completed_at
            else None
        ),
        "errorMessage": document.error_message,
    }


def create_document_record(
    document_id: str,
    filename: str,
    document_type: str,
) -> dict:
    with SessionLocal() as session:
        document = Document(
            document_id=document_id,
            filename=filename,
            status="uploaded",
            document_type=document_type,
            subject_name="",
            subject_prison_number="",
            other_phrases="",
        )

        session.add(document)
        session.commit()
        session.refresh(document)

        return document_to_dict(document)


def get_document(document_id: str) -> dict | None:
    with SessionLocal() as session:
        document = session.get(Document, document_id)

        if document is None:
            return None

        return document_to_dict(document)


def get_document_or_404(document_id: str) -> dict:
    document = get_document(document_id)

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    return document


def update_document_record(
    document_id: str,
    *,
    status: str | None = None,
    processing_job_id: str | None = None,
    processing_attempt_count: int | None = None,
    processing_claim_id: str | None = None,
    processing_lease_expires_at: datetime | None = None,
    subject_name: str | None = None,
    subject_prison_number: str | None = None,
    other_phrases: str | None = None,
    processing_started_at: datetime | None = None,
    processing_completed_at: datetime | None = None,
    redaction_started_at: datetime | None = None,
    redaction_completed_at: datetime | None = None,
    error_message: str | None = None,
    clear_error: bool = False,
) -> dict:
    with SessionLocal() as session:
        document = session.get(Document, document_id)

        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")

        if status is not None:
            document.status = status

        if processing_job_id is not None:
            document.processing_job_id = processing_job_id

        if processing_attempt_count is not None:
            document.processing_attempt_count = processing_attempt_count

        if processing_claim_id is not None:
            document.processing_claim_id = processing_claim_id

        if processing_lease_expires_at is not None:
            document.processing_lease_expires_at = processing_lease_expires_at

        if subject_name is not None:
            document.subject_name = subject_name

        if subject_prison_number is not None:
            document.subject_prison_number = subject_prison_number

        if other_phrases is not None:
            document.other_phrases = other_phrases

        if processing_started_at is not None:
            document.processing_started_at = processing_started_at

        if processing_completed_at is not None:
            document.processing_completed_at = processing_completed_at

        if redaction_started_at is not None:
            document.redaction_started_at = redaction_started_at

        if redaction_completed_at is not None:
            document.redaction_completed_at = redaction_completed_at

        if error_message is not None:
            document.error_message = error_message

        if clear_error:
            document.error_message = None

        session.commit()
        session.refresh(document)

        return document_to_dict(document)


def try_claim_document_processing(
    *,
    document_id: str,
    job_id: str,
    claim_id: str,
    attempt_count: int,
    lease_expires_at: datetime,
) -> bool:
    now = datetime.now(timezone.utc)

    with SessionLocal() as session:
        result = session.execute(
            update(Document)
            .where(
                Document.document_id == document_id,
                Document.processing_job_id == job_id,
                or_(
                    Document.status.in_(["enqueueing", "queued", "retrying"]),
                    and_(
                        Document.status == "processing",
                        or_(
                            Document.processing_lease_expires_at.is_(None),
                            Document.processing_lease_expires_at <= now,
                        ),
                    ),
                ),
            )
            .values(
                status="processing",
                processing_claim_id=claim_id,
                processing_attempt_count=attempt_count,
                processing_lease_expires_at=lease_expires_at,
                processing_started_at=now,
                processing_completed_at=None,
                error_message=None,
            )
        )

        session.commit()

        return result.rowcount == 1


def renew_document_processing_lease(
    *,
    document_id: str,
    job_id: str,
    claim_id: str,
    lease_expires_at: datetime,
) -> bool:
    with SessionLocal() as session:
        result = session.execute(
            update(Document)
            .where(
                Document.document_id == document_id,
                Document.processing_job_id == job_id,
                Document.processing_claim_id == claim_id,
                Document.status == "processing",
            )
            .values(
                processing_lease_expires_at=lease_expires_at,
            )
        )

        session.commit()

        return result.rowcount == 1


def complete_document_processing(
    *,
    document_id: str,
    job_id: str,
    claim_id: str,
    completed_at: datetime,
) -> bool:
    with SessionLocal() as session:
        result = session.execute(
            update(Document)
            .where(
                Document.document_id == document_id,
                Document.processing_job_id == job_id,
                Document.processing_claim_id == claim_id,
                Document.status == "processing",
            )
            .values(
                status="ready_for_review",
                processing_completed_at=completed_at,
                processing_claim_id=None,
                processing_lease_expires_at=None,
                error_message=None,
            )
        )

        session.commit()

        return result.rowcount == 1


def fail_document_processing_attempt(
    *,
    document_id: str,
    job_id: str,
    claim_id: str,
    terminal: bool,
) -> bool:
    with SessionLocal() as session:
        result = session.execute(
            update(Document)
            .where(
                Document.document_id == document_id,
                Document.processing_job_id == job_id,
                Document.processing_claim_id == claim_id,
                Document.status == "processing",
            )
            .values(
                status="failed" if terminal else "retrying",
                processing_completed_at=(
                    datetime.now(timezone.utc) if terminal else None
                ),
                processing_claim_id=None,
                processing_lease_expires_at=None,
            )
        )

        session.commit()

        return result.rowcount == 1


def mark_document_processing_queued(
    *,
    document_id: str,
    job_id: str,
) -> bool:
    with SessionLocal() as session:
        result = session.execute(
            update(Document)
            .where(
                Document.document_id == document_id,
                Document.processing_job_id == job_id,
                Document.status == "enqueueing",
            )
            .values(
                status="queued",
            )
        )

        session.commit()

        return result.rowcount == 1


def try_start_document_processing_enqueue(
    *,
    document_id: str,
    job_id: str,
    subject_name: str,
    subject_prison_number: str,
    other_phrases: str,
) -> bool:
    with SessionLocal() as session:
        result = session.execute(
            update(Document)
            .where(
                Document.document_id == document_id,
                Document.status.in_(
                    [
                        "uploaded",
                        "enqueue_failed",
                        "failed",
                    ]
                ),
            )
            .values(
                status="enqueueing",
                processing_job_id=job_id,
                processing_attempt_count=0,
                processing_claim_id=None,
                processing_lease_expires_at=None,
                processing_started_at=None,
                processing_completed_at=None,
                subject_name=subject_name,
                subject_prison_number=subject_prison_number,
                other_phrases=other_phrases,
                error_message=None,
            )
        )

        session.commit()

        return result.rowcount == 1
