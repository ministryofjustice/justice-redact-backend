import json
import shutil
from pathlib import Path

from fastapi import UploadFile

from app.core.paths import DECISIONS_DIR, EXPORTS_DIR, PROCESSED_DIR, UPLOAD_DIR


def upload_pdf_path(document_id: str) -> Path:
    return UPLOAD_DIR / f"{document_id}.pdf"


def processed_review_path(document_id: str) -> Path:
    return PROCESSED_DIR / f"{document_id}.json"


def decisions_path(document_id: str) -> Path:
    return DECISIONS_DIR / f"{document_id}.json"


def export_pdf_path(document_id: str) -> Path:
    return EXPORTS_DIR / f"{document_id}-redacted.pdf"


def save_upload_file(file: UploadFile, destination: Path) -> None:
    with destination.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)


def write_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
