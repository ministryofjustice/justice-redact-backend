from fastapi import HTTPException
from datetime import datetime

from app.core.database import SessionLocal
from app.models.document import Document


def document_to_dict(document: Document) -> dict:
    return {
        "documentId": document.document_id,
        "filename": document.filename,
        "status": document.status,
        "documentType": document.document_type,
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
