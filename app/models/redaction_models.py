from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TextRedactionDecision(BaseModel):
    kind: Literal["text"]
    pageNumber: int
    itemId: str
    start: int
    end: int
    text: str
    action: Literal["redact"]
    source: Literal["manual"]
    redactionGroupId: str | None = None


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
    redactionGroupId: str | None = None


class ImageRedactionDecision(BaseModel):
    kind: Literal["image"]
    pageNumber: int
    imageId: str
    action: Literal["redact"]
    source: Literal["manual"]


class ImageAreaRect(BaseModel):
    """Normalized rectangle relative to an image's PDF bounding box."""

    model_config = ConfigDict(extra="forbid")

    x0: float = Field(ge=0, le=1, allow_inf_nan=False)
    y0: float = Field(ge=0, le=1, allow_inf_nan=False)
    x1: float = Field(ge=0, le=1, allow_inf_nan=False)
    y1: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_positive_area(self):
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError(
                "Image area must have positive width and height"
            )
        return self


class ImageAreaRedactionDecision(BaseModel):
    """One independently persisted partial-image redaction."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["image_area"]
    pageNumber: int = Field(ge=1)
    imageId: str = Field(min_length=1, max_length=512)
    areaId: str = Field(min_length=1, max_length=128)
    rect: ImageAreaRect
    action: Literal["redact"]
    source: Literal["manual"]

    @field_validator("imageId", "areaId")
    @classmethod
    def validate_nonblank_identifier(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Image identifiers cannot be blank")
        return value


class PageDecision(BaseModel):
    kind: Literal["page"]
    pageNumber: int
    action: Literal["exempt", "delete"]
    source: Literal["manual"]


RedactionDecision = (
    TextRedactionDecision
    | TableRedactionDecision
    | ImageRedactionDecision
    | ImageAreaRedactionDecision
    | PageDecision
)


class ApplyRedactionsRequest(BaseModel):
    documentId: str
    decisions: list[RedactionDecision]
    expectedRevision: int


class SaveRedactionDecisionsRequest(BaseModel):
    documentId: str
    decisions: list[RedactionDecision]
    expectedRevision: int
