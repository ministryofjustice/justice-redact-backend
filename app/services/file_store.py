import shutil
from pathlib import Path

from fastapi import UploadFile

from app.services.s3_keys import original_pdf_key
from app.services.s3_service import upload_file_to_s3


def save_upload_file(
    file: UploadFile,
    document_id: str,
) -> None:
    filename = file.filename or "document.pdf"
    temp_path = Path("/tmp") / f"{document_id}.pdf"

    with temp_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    upload_file_to_s3(
        temp_path,
        original_pdf_key(document_id, filename),
    )
