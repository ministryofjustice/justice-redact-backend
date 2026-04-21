from justice_redact.detection import detect_for_review

from app.services.document_store import get_document
from app.services.file_store import processed_review_path, upload_pdf_path, write_json


async def process_document_pipeline(document_id: str) -> None:
    document = get_document(document_id)
    if not document:
        return

    try:
        pdf_path = str(upload_pdf_path(document_id))

        other_phrases_list = [
            phrase.strip()
            for phrase in document["otherPhrases"].split(",")
            if phrase.strip()
        ]

        result = detect_for_review(
            pdf_path=pdf_path,
            subject_name=document["subjectName"],
            subject_prison_number=document["subjectPrisonNumber"],
            other_phrases=other_phrases_list,
        )

        result["documentId"] = document_id
        result["filename"] = document["filename"]
        result["status"] = "ready_for_review"

        write_json(processed_review_path(document_id), result)

        document["status"] = "ready_for_review"

    except Exception as exc:
        document["status"] = "failed"
        document["error"] = str(exc)
