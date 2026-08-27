def document_prefix(document_id: str) -> str:
    return f"documents/{document_id}/"


def redaction_run_prefix(
    document_id: str,
    run_id: str,
) -> str:
    return f"documents/{document_id}/redaction-runs/{run_id}/"


def redaction_run_redacted_pdf_key(
    document_id: str,
    run_id: str,
) -> str:
    return f"{redaction_run_prefix(document_id, run_id)}" "exports/redacted.pdf"


def redaction_run_vetted_pdf_key(
    document_id: str,
    run_id: str,
) -> str:
    return f"{redaction_run_prefix(document_id, run_id)}" "exports/vetted.pdf"


def redaction_run_exempt_pdf_key(
    document_id: str,
    run_id: str,
) -> str:
    return f"{redaction_run_prefix(document_id, run_id)}" "exports/_exempt.pdf"


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


def document_geometry_manifest_key(document_id: str) -> str:
    return f"documents/{document_id}/geometry/manifest.json"


def document_geometry_chunk_key(document_id: str, chunk_index: int) -> str:
    return f"documents/{document_id}/geometry/chunks/{chunk_index:04d}.json"
