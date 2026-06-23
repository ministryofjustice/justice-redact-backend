from typing import Literal

from pydantic import BaseModel


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


class PageDecision(BaseModel):
    kind: Literal["page"]
    pageNumber: int
    action: Literal["exempt", "delete"]
    source: Literal["manual"]


RedactionDecision = (
    TextRedactionDecision
    | TableRedactionDecision
    | ImageRedactionDecision
    | PageDecision
)


class ApplyRedactionsRequest(BaseModel):
    documentId: str
    decisions: list[RedactionDecision]
