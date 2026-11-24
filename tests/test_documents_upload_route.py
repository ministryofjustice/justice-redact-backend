from io import BytesIO

import pytest
from starlette.datastructures import Headers

from app.api.routers import documents
from app.services.auth_service import AuthenticatedUser


@pytest.mark.anyio
async def test_upload_document_assigns_authenticated_user_as_owner(
    monkeypatch,
):
    uploaded_file = documents.UploadFile(
        filename="example.pdf",
        file=BytesIO(b"%PDF-1.7"),
        headers=Headers(
            {
                "content-type": "application/pdf",
            }
        ),
    )

    monkeypatch.setattr(
        documents,
        "uuid4",
        lambda: "document-123",
    )

    saved_uploads = []

    monkeypatch.setattr(
        documents,
        "save_upload_file",
        lambda *, file, document_id: (
            saved_uploads.append(
                {
                    "file": file,
                    "document_id": document_id,
                }
            )
        ),
    )

    created_documents = []

    def fake_create_document_record(
        *,
        document_id,
        owner_user_id,
        filename,
        document_type,
        warning_reason,
    ):
        created_documents.append(
            {
                "document_id": document_id,
                "owner_user_id": owner_user_id,
                "filename": filename,
                "document_type": document_type,
                "warning_reason": warning_reason,
            }
        )

        return {
            "documentId": document_id,
        }

    monkeypatch.setattr(
        documents,
        "create_document_record",
        fake_create_document_record,
    )

    current_user = AuthenticatedUser(
        user_id="user-123",
        email="user@justice.gov.uk",
    )

    response = await documents.upload_document(
        file=uploaded_file,
        document_type="nomis",
        warning_reason=None,
        current_user=current_user,
    )

    assert response == {
        "documentId": "document-123",
        "status": "uploaded",
    }

    assert len(saved_uploads) == 1

    assert saved_uploads[0]["document_id"] == "document-123"

    assert created_documents == [
        {
            "document_id": "document-123",
            "owner_user_id": "user-123",
            "filename": "example.pdf",
            "document_type": "nomis",
            "warning_reason": None,
        }
    ]


@pytest.mark.anyio
async def test_upload_document_rejects_non_pdf_before_storage(
    monkeypatch,
):
    uploaded_file = documents.UploadFile(
        filename="example.txt",
        file=BytesIO(b"not a pdf"),
        headers=Headers(
            {
                "content-type": "text/plain",
            }
        ),
    )

    storage_called = False

    def fake_save_upload_file(
        *,
        file,
        document_id,
    ):
        nonlocal storage_called
        storage_called = True

    monkeypatch.setattr(
        documents,
        "save_upload_file",
        fake_save_upload_file,
    )

    current_user = AuthenticatedUser(
        user_id="user-123",
        email="user@justice.gov.uk",
    )

    with pytest.raises(documents.HTTPException) as exc_info:
        await documents.upload_document(
            file=uploaded_file,
            document_type="nomis",
            warning_reason=None,
            current_user=current_user,
        )

    assert exc_info.value.status_code == 400
    assert storage_called is False


def test_upload_endpoint_requires_authentication():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(documents.router)

    client = TestClient(app)

    response = client.post(
        "/documents/upload",
        files={
            "file": (
                "example.pdf",
                b"%PDF-1.7",
                "application/pdf",
            ),
        },
        data={
            "documentType": "nomis",
        },
    )

    assert response.status_code == 401

    assert response.json() == {
        "detail": "Authentication required",
    }
