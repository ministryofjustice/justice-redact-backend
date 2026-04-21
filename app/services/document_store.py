from fastapi import HTTPException

DOCUMENT_STATUS_STORE: dict[str, dict] = {}


def create_document_record(document_id: str, filename: str) -> dict:

    record = {
        "documentId": document_id,
        "filename": filename,
        "status": "uploaded",
        "subjectName": "",
        "subjectPrisonNumber": "",
        "otherPhrases": "",
    }

    DOCUMENT_STATUS_STORE[document_id] = record

    return record


def get_document(document_id: str) -> dict | None:

    return DOCUMENT_STATUS_STORE.get(document_id)


def get_document_or_404(document_id: str) -> dict:

    document = get_document(document_id)

    if not document:

        raise HTTPException(status_code=404, detail="Document not found")

    return document
