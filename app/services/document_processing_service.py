from justice_redact.detection import detect_for_review

from app.services.document_store import get_document
from app.services.review_result_store import upsert_review_result
from app.services.s3_service import download_file_from_s3
from pathlib import Path
from justice_redact.pdf_handler.images import render_pdf_region_to_png
import traceback


async def process_document_pipeline(document_id: str) -> None:
    document = get_document(document_id)
    if not document:
        return

    try:
        temp_pdf_path = Path("/tmp") / f"{document_id}.pdf"

        download_file_from_s3(
            f"documents/{document_id}/original/{document['filename']}",
            temp_pdf_path,
        )

        pdf_path = str(temp_pdf_path)

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

        image_preview_dir = Path("/tmp") / "processed" / document_id / "images"
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

        result["documentId"] = document_id
        result["filename"] = document["filename"]
        result["status"] = "ready_for_review"

        upsert_review_result(
            document_id=document_id,
            review_json=result,
        )

        document["status"] = "ready_for_review"

    except Exception as exc:
        traceback.print_exc()

        from app.services.document_store import update_document_record

        update_document_record(
            document_id,
            status="failed",
        )
