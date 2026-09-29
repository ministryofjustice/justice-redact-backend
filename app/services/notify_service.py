from notifications_python_client.notifications import NotificationsAPIClient

from app.core.settings import settings


class NotifyConfigurationError(RuntimeError):
    pass


def send_verification_email(
    *,
    email: str,
    verification_link: str,
) -> str:
    """
    Send the Justice Redact email verification link through GOV.UK Notify.

    The Notify client is deliberately created only when this function is
    called so migration jobs and background workers do not require Notify
    configuration simply to start.
    """

    if not settings.notify_api_key:
        raise NotifyConfigurationError(
            "GOV.UK Notify API key is not configured"
        )

    if not settings.notify_verification_template_id:
        raise NotifyConfigurationError(
            "GOV.UK Notify verification template ID is not configured"
        )

    client = NotificationsAPIClient(
        settings.notify_api_key
    )

    response = client.send_email_notification(
        email_address=email,
        template_id=settings.notify_verification_template_id,
        personalisation={
            "verification_link": verification_link,
        },
    )

    return response["id"]
