from app.services import s3_service


def test_delete_s3_prefix_deletes_every_object_under_prefix(monkeypatch):
    class FakePaginator:
        def paginate(self, **kwargs):
            assert kwargs == {
                "Bucket": s3_service._BUCKET,
                "Prefix": "documents/document-123/",
            }

            return [
                {
                    "Contents": [
                        {"Key": "documents/document-123/original/file.pdf"},
                        {"Key": "documents/document-123/previews/image-1.png"},
                    ]
                },
                {
                    "Contents": [
                        {"Key": "documents/document-123/geometry/manifest.json"},
                    ]
                },
            ]

    delete_calls = []

    monkeypatch.setattr(
        s3_service.s3_client,
        "get_paginator",
        lambda operation: (
            FakePaginator()
            if operation == "list_objects_v2"
            else None
        ),
    )

    monkeypatch.setattr(
        s3_service.s3_client,
        "delete_objects",
        lambda **kwargs: delete_calls.append(kwargs),
    )

    s3_service.delete_s3_prefix(
        "documents/document-123/"
    )

    assert delete_calls == [
        {
            "Bucket": s3_service._BUCKET,
            "Delete": {
                "Objects": [
                    {"Key": "documents/document-123/original/file.pdf"},
                    {"Key": "documents/document-123/previews/image-1.png"},
                ],
                "Quiet": True,
            },
        },
        {
            "Bucket": s3_service._BUCKET,
            "Delete": {
                "Objects": [
                    {"Key": "documents/document-123/geometry/manifest.json"},
                ],
                "Quiet": True,
            },
        },
    ]


def test_delete_s3_prefix_is_safe_when_prefix_is_empty(monkeypatch):
    class FakePaginator:
        def paginate(self, **kwargs):
            return [{}]

    delete_calls = []

    monkeypatch.setattr(
        s3_service.s3_client,
        "get_paginator",
        lambda operation: FakePaginator(),
    )

    monkeypatch.setattr(
        s3_service.s3_client,
        "delete_objects",
        lambda **kwargs: delete_calls.append(kwargs),
    )

    s3_service.delete_s3_prefix(
        "documents/document-123/"
    )

    assert delete_calls == []
