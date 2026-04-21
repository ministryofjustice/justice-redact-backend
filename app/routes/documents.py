from __future__ import annotations
import asyncio
import json
import shutil
from pathlib import Path
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from justice_redact.detection import detect_for_review
from justice_redact.pdf_handler import extract_document
from justice_redact.pdf_handler.apply import apply_pdf_decisions
from justice_redact.pdf_handler.decisions import (
    ImageRegionDecision,
    TableTextSpanDecision,
    TextSpanDecision,
)

router = APIRouter(prefix="/documents", tags=["documents"])

UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

PROCESSED_DIR = Path("data/processed")
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

DECISIONS_DIR = Path("data/decisions")
DECISIONS_DIR.mkdir(parents=True, exist_ok=True)

EXPORTS_DIR = Path("data/exports")
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

DOCUMENT_STATUS_STORE: dict[str, dict] = {}


class ProcessDocumentRequest(BaseModel):
    subjectName: str = ""
    subjectPrisonNumber: str = ""
    otherPhrases: str = ""


class TextRedactionDecision(BaseModel):
    kind: Literal["text"]
    pageNumber: int
    itemId: str
    start: int
    end: int
    text: str
    action: Literal["redact"]
    source: Literal["manual"]


class TableRedactionDecision(BaseModel):
    kind: Literal["table_cell"]
    pageNumber: int
    tableId: str
    cellId: str
    start: int
    end: int
    text: str
    action: Literal["redact"]
    source: Literal["manual"]


class ImageRedactionDecision(BaseModel):
    kind: Literal["image"]
    pageNumber: int
    imageId: str
    action: Literal["redact"]
    source: Literal["manual"]


RedactionDecision = (
    TextRedactionDecision | TableRedactionDecision | ImageRedactionDecision
)


class ApplyRedactionsRequest(BaseModel):
    documentId: str
    decisions: list[RedactionDecision]


def _build_pdf_handler_decisions(document_model, decisions: list[RedactionDecision]):
    typed_decisions = []

    for decision in decisions:
        if isinstance(decision, TextRedactionDecision):
            typed_decisions.append(
                TextSpanDecision(
                    document_id=document_model.document_id,
                    page_number=decision.pageNumber,
                    item_id=decision.itemId,
                    start=decision.start,
                    end=decision.end,
                    text=decision.text,
                    source=decision.source,
                    action=decision.action,
                )
            )
            continue

        if isinstance(decision, TableRedactionDecision):
            typed_decisions.append(
                TableTextSpanDecision(
                    document_id=document_model.document_id,
                    page_number=decision.pageNumber,
                    table_id=decision.tableId,
                    cell_id=decision.cellId,
                    start=decision.start,
                    end=decision.end,
                    text=decision.text,
                    source=decision.source,
                    action=decision.action,
                )
            )
            continue

        if isinstance(decision, ImageRedactionDecision):
            typed_decisions.append(
                ImageRegionDecision(
                    document_id=document_model.document_id,
                    page_number=decision.pageNumber,
                    image_id=decision.imageId,
                    source=decision.source,
                    action=decision.action,
                )
            )
            continue

    return typed_decisions


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    document_id = str(uuid4())
    file_path = UPLOAD_DIR / f"{document_id}.pdf"

    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    DOCUMENT_STATUS_STORE[document_id] = {
        "documentId": document_id,
        "filename": file.filename,
        "status": "uploaded",
        "subjectName": "",
        "subjectPrisonNumber": "",
        "otherPhrases": "",
    }

    return {
        "documentId": document_id,
        "status": "uploaded",
    }


@router.post("/{document_id}/process")
async def process_document(document_id: str, request: ProcessDocumentRequest):
    document = DOCUMENT_STATUS_STORE.get(document_id)

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    document["subjectName"] = request.subjectName
    document["subjectPrisonNumber"] = request.subjectPrisonNumber
    document["otherPhrases"] = request.otherPhrases
    document["status"] = "processing"

    asyncio.create_task(process_document_pipeline(document_id))

    return {
        "documentId": document_id,
        "status": "processing",
    }


@router.get("/{document_id}/status")
async def get_document_status(document_id: str):
    document = DOCUMENT_STATUS_STORE.get(document_id)

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    return document


@router.get("/{document_id}/review")
async def get_document_review(document_id: str):
    document = DOCUMENT_STATUS_STORE.get(document_id)

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    processed_path = PROCESSED_DIR / f"{document_id}.json"

    if not processed_path.exists():
        raise HTTPException(status_code=404, detail="Processed review data not found")

    with processed_path.open("r", encoding="utf-8") as f:
        return json.load(f)


@router.post("/{document_id}/apply-redactions")
async def apply_redactions(document_id: str, request: ApplyRedactionsRequest):
    document = DOCUMENT_STATUS_STORE.get(document_id)

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document_id != request.documentId:
        raise HTTPException(status_code=400, detail="Document ID mismatch")

    if not request.decisions:
        raise HTTPException(status_code=400, detail="No redaction decisions supplied")

    decisions_path = DECISIONS_DIR / f"{document_id}.json"
    with decisions_path.open("w", encoding="utf-8") as f:
        json.dump(request.model_dump(), f, indent=2)

    pdf_path = UPLOAD_DIR / f"{document_id}.pdf"
    export_path = EXPORTS_DIR / f"{document_id}-redacted.pdf"

    try:
        document_model = extract_document(pdf_path)
        typed_decisions = _build_pdf_handler_decisions(
            document_model=document_model,
            decisions=request.decisions,
        )

        if not typed_decisions:
            raise HTTPException(
                status_code=400,
                detail="No valid redaction decisions could be built",
            )

        apply_pdf_decisions(
            document=document_model,
            pdf_path=pdf_path,
            decisions=typed_decisions,
            output_path=export_path,
        )

        summary = {
            "totalDecisionsApplied": len(typed_decisions),
            "decisionTypes": sorted({decision.kind for decision in request.decisions}),
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    document["status"] = "redaction_complete"
    document["exportPath"] = str(export_path)
    document["redactionSummary"] = summary

    return {
        "documentId": document_id,
        "status": "redaction_complete",
        "exportPath": str(export_path),
        "summary": summary,
    }


@router.get("/{document_id}/export")
async def get_document_export(document_id: str):
    document = DOCUMENT_STATUS_STORE.get(document_id)

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    export_path = EXPORTS_DIR / f"{document_id}-redacted.pdf"

    if not export_path.exists():
        raise HTTPException(status_code=404, detail="Exported file not found")

    processed_path = PROCESSED_DIR / f"{document_id}.json"
    page_count = None

    if processed_path.exists():
        with processed_path.open("r", encoding="utf-8") as f:
            processed_data = json.load(f)
            page_count = processed_data.get("summary", {}).get("totalPages")

    return {
        "documentId": document_id,
        "filename": document["filename"],
        "status": "redaction_complete",
        "exportUrl": f"{router.prefix}/{document_id}/export-file",
        "pageCount": page_count,
    }


@router.get("/{document_id}/export-file")
async def download_export_file(document_id: str):
    document = DOCUMENT_STATUS_STORE.get(document_id)

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    export_path = EXPORTS_DIR / f"{document_id}-redacted.pdf"

    if not export_path.exists():
        raise HTTPException(status_code=404, detail="Exported file not found")

    original_name = document.get("filename", "redacted.pdf")
    download_name = original_name.replace(".pdf", "_redacted.pdf")

    return FileResponse(
        path=export_path,
        media_type="application/pdf",
        filename=download_name,
    )


async def process_document_pipeline(document_id: str):
    document = DOCUMENT_STATUS_STORE.get(document_id)

    if not document:
        return

    try:
        pdf_path = str(UPLOAD_DIR / f"{document_id}.pdf")

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

        processed_path = PROCESSED_DIR / f"{document_id}.json"
        with processed_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        document["status"] = "ready_for_review"

    except Exception as exc:
        document["status"] = "failed"
        document["error"] = str(exc)
