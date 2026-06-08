from pathlib import Path

from justice_redact.detection import detect_for_review
from justice_redact.pdf_handler.images import render_pdf_region_to_png

from app.services.comprehend_service import detect_pii_entities
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

        image_preview_dir = Path("data/processed") / document_id / "images"
        image_preview_dir.mkdir(parents=True, exist_ok=True)

        for page in result.get("pages", []):
            for image in page.get("images", []):
                bbox = image.get("bbox")

                if not bbox:
                    continue

                output_path = image_preview_dir / f"{image['imageId']}.png"

                render_pdf_region_to_png(
                    pdf_path=pdf_path,
                    page_number=page["pageNumber"],
                    bbox=type(
                        "BBoxLike",
                        (),
                        {
                            "x0": bbox["x0"],
                            "y0": bbox["y0"],
                            "x1": bbox["x1"],
                            "y1": bbox["y1"],
                        },
                    )(),
                    output_path=output_path,
                )

                image["imageUrl"] = (
                    f"/documents/{document_id}/images/{image['imageId']}.png"
                )

        # ---------------------------------------------------------------------------
        # ADDED: Comprehend PII detection
        # Extract all text from the result pages and run it through AWS Comprehend.
        # The detected PII entities are added to the result under "comprehendEntities"
        # and will be returned as part of the GET /{document_id}/review response.
        #
        # If Comprehend fails (e.g. AP role not yet configured, network issue),
        # we log the error and continue — the review result is still written
        # so the rest of the pipeline is not blocked.
        # ---------------------------------------------------------------------------
        full_text = _extract_full_text(result)

        if full_text.strip():
            try:
                comprehend_response = detect_pii_entities(full_text)
                result["comprehendEntities"] = comprehend_response.get("Entities", [])
            except Exception as comprehend_exc:
                # Non-fatal: surface the error in the result but don't fail the pipeline
                result["comprehendEntities"] = []
                result["comprehendError"] = str(comprehend_exc)
        else:
            result["comprehendEntities"] = []

        result["documentId"] = document_id
        result["filename"] = document["filename"]
        result["status"] = "ready_for_review"

        write_json(processed_review_path(document_id), result)

        document["status"] = "ready_for_review"

    except Exception as exc:
        document["status"] = "failed"
        document["error"] = str(exc)


def _extract_full_text(result: dict) -> str:
    """
    Pulls all text spans from the detect_for_review result into a single string
    for Comprehend to analyse. Comprehend needs plain text, not structured JSON.
    """
    text_parts = []

    for page in result.get("pages", []):
        for block in page.get("textBlocks", []):
            text = block.get("text", "").strip()
            if text:
                text_parts.append(text)

        for table in page.get("tables", []):
            for row in table.get("rows", []):
                for cell in row.get("cells", []):
                    text = cell.get("text", "").strip()
                    if text:
                        text_parts.append(text)

    return " ".join(text_parts)
