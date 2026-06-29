def original_pdf_key(document_id: str, filename: str) -> str:
    return f"documents/{document_id}/original/{filename}"


def preview_image_key(document_id: str, image_id: str) -> str:
    return f"documents/{document_id}/previews/{image_id}.png"


def redacted_pdf_key(document_id: str) -> str:
    return f"documents/{document_id}/exports/redacted.pdf"


def vetted_pdf_key(document_id: str) -> str:
    return f"documents/{document_id}/exports/vetted.pdf"


def exempt_pdf_key(document_id: str) -> str:
    return f"documents/{document_id}/exports/_exempt.pdf"


def document_geometry_key(document_id: str) -> str:
    return f"documents/{document_id}/geometry/document.json"
