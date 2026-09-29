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

    with pytest.raises(
        notify_service.NotifyConfigurationError
    ):
        notify_service.send_verification_email(
            email="user@justice.gov.uk",
            verification_link=(
                "https://example.test/confirm"
            ),
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
            captured["email_address"] = (
                email_address
            )
            captured["template_id"] = (
                template_id
            )
            captured["personalisation"] = (
                personalisation
            )

            return {
                "id": "notification-123",
            }

    monkeypatch.setattr(
        notify_service,
        "NotificationsAPIClient",
        FakeClient,
    )

    notification_id = (
        notify_service
        .send_verification_email(
            email="user@justice.gov.uk",
            verification_link=(
                "https://example.test/"
                "confirm-email#token=secret"
            ),
        )
    )

    assert notification_id == (
        "notification-123"
    )

    assert captured == {
        "api_key": "notify-key",
        "email_address": (
            "user@justice.gov.uk"
        ),
        "template_id": "template-123",
        "personalisation": {
            "verification_link": (
                "https://example.test/"
                "confirm-email#token=secret"
            ),
        },
    }
