from fastapi import HTTPException

from app.core.database import SessionLocal
from app.models.document import Document


def document_to_dict(document: Document) -> dict:
    return {
        "documentId": document.document_id,
        "filename": document.filename,
        "status": document.status,
        "subjectName": document.subject_name,
        "subjectPrisonNumber": document.subject_prison_number,
        "otherPhrases": document.other_phrases,
    }


def create_document_record(document_id: str, filename: str) -> dict:
    with SessionLocal() as session:
        document = Document(
            document_id=document_id,
            filename=filename,
            status="uploaded",
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
