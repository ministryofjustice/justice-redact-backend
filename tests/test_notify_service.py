import pytest

from app.services import notify_service


def test_send_verification_email_requires_api_key(
    monkeypatch,
):
    monkeypatch.setattr(
        notify_service.settings,
        "notify_api_key",
        None,
    )

    monkeypatch.setattr(
        notify_service.settings,
        "notify_verification_template_id",
        "template-123",
    )

    with pytest.raises(notify_service.NotifyConfigurationError):
        notify_service.send_verification_email(
            email="user@justice.gov.uk",
            verification_link=("https://example.test/confirm"),
        )


def test_send_verification_email_uses_notify_template(
    monkeypatch,
):
    monkeypatch.setattr(
        notify_service.settings,
        "notify_api_key",
        "notify-key",
    )

    monkeypatch.setattr(
        notify_service.settings,
        "notify_verification_template_id",
        "template-123",
    )

    captured = {}

    class FakeClient:
        def __init__(self, api_key):
            captured["api_key"] = api_key

        def send_email_notification(
            self,
            *,
            email_address,
            template_id,
            personalisation,
        ):
            captured["email_address"] = email_address
            captured["template_id"] = template_id
            captured["personalisation"] = personalisation

            return {
                "id": "notification-123",
            }

    monkeypatch.setattr(
        notify_service,
        "NotificationsAPIClient",
        FakeClient,
    )

    notification_id = notify_service.send_verification_email(
        email="user@justice.gov.uk",
        verification_link=("https://example.test/" "confirm-email#token=secret"),
    )

    assert notification_id == ("notification-123")

    assert captured == {
        "api_key": "notify-key",
        "email_address": ("user@justice.gov.uk"),
        "template_id": "template-123",
        "personalisation": {
            "verification_link": ("https://example.test/" "confirm-email#token=secret"),
        },
    }


def test_send_document_ready_email_requires_template_id(
    monkeypatch,
):
    monkeypatch.setattr(
        notify_service.settings,
        "notify_api_key",
        "notify-key",
    )

    monkeypatch.setattr(
        notify_service.settings,
        "notify_document_ready_template_id",
        None,
    )

    with pytest.raises(notify_service.NotifyConfigurationError):
        notify_service.send_document_ready_email(
            email="user@justice.gov.uk",
            filename="document.pdf",
            document_link=("https://example.test/" "review?documentId=document-123"),
        )


def test_send_document_ready_email_uses_notify_template(
    monkeypatch,
):
    monkeypatch.setattr(
        notify_service.settings,
        "notify_api_key",
        "notify-key",
    )

    monkeypatch.setattr(
        notify_service.settings,
        "notify_document_ready_template_id",
        "ready-template-123",
    )

    captured = {}

    class FakeClient:
        def __init__(self, api_key):
            captured["api_key"] = api_key

        def send_email_notification(
            self,
            *,
            email_address,
            template_id,
            personalisation,
        ):
            captured["email_address"] = email_address
            captured["template_id"] = template_id
            captured["personalisation"] = personalisation

            return {
                "id": "notification-456",
            }

    monkeypatch.setattr(
        notify_service,
        "NotificationsAPIClient",
        FakeClient,
    )

    notification_id = notify_service.send_document_ready_email(
        email="user@justice.gov.uk",
        filename="document.pdf",
        document_link=("https://example.test/" "review?documentId=document-123"),
    )

    assert notification_id == ("notification-456")

    assert captured == {
        "api_key": "notify-key",
        "email_address": ("user@justice.gov.uk"),
        "template_id": ("ready-template-123"),
        "personalisation": {
            "filename": "document.pdf",
            "document_link": ("https://example.test/" "review?documentId=document-123"),
        },
    }
