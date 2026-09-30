from datetime import (
    datetime,
    timezone,
)

import pytest

from app.api.routers import auth
from app.services.auth_service import (
    AccessNotEnabledError,
    AuthenticatedUser,
    VerificationChallenge,
    VerifiedSession,
)


@pytest.mark.anyio
async def test_request_verification_sends_email_and_sets_browser_cookie(
    monkeypatch,
):
    challenge = VerificationChallenge(
        verification_id="verification-123",
        email="user@justice.gov.uk",
        email_token="email-secret",
        browser_token="browser-secret",
        expires_at=datetime(
            2026,
            9,
            29,
            12,
            30,
            tzinfo=timezone.utc,
        ),
    )

    monkeypatch.setattr(
        auth,
        "create_verification_challenge",
        lambda email: challenge,
    )

    captured = {}

    def fake_send(
        *,
        email,
        verification_link,
    ):
        captured["email"] = email
        captured["link"] = verification_link

        return "notification-123"

    monkeypatch.setattr(
        auth,
        "send_verification_email",
        fake_send,
    )

    from fastapi import Response

    response = Response()

    result = await auth.request_verification(
        auth.RequestVerificationRequest(email="user@justice.gov.uk"),
        response,
    )

    assert result == {
        "status": ("verification_email_sent"),
    }

    assert captured["email"] == ("user@justice.gov.uk")

    assert "#token=email-secret" in captured["link"]

    cookie = response.headers["set-cookie"]

    assert auth.settings.auth_verification_cookie_name in cookie

    assert "browser-secret" in cookie
    assert "HttpOnly" in cookie


@pytest.mark.anyio
async def test_verify_rejects_user_without_access(
    monkeypatch,
):
    def reject_access(
        email_token,
        browser_token,
    ):
        raise auth.AccessNotEnabledError

    monkeypatch.setattr(
        auth,
        "verify_email_token",
        reject_access,
    )

    from fastapi import HTTPException
    from fastapi import Response

    with pytest.raises(HTTPException) as exc_info:
        await auth.verify_email(
            auth.VerifyEmailRequest(token="email-secret"),
            Response(),
            browser_token="browser-secret",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "You cannot use Justice Redact yet"


@pytest.mark.anyio
async def test_verify_sets_session_cookie(
    monkeypatch,
):
    verified = VerifiedSession(
        user=AuthenticatedUser(
            user_id="user-123",
            email="user@justice.gov.uk",
        ),
        token="session-secret",
        expires_at=datetime(
            2026,
            10,
            6,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    )

    monkeypatch.setattr(
        auth,
        "verify_email_token",
        lambda email_token, browser_token: (verified),
    )

    from fastapi import Response

    response = Response()

    result = await auth.verify_email(
        auth.VerifyEmailRequest(token="email-secret"),
        response,
        browser_token="browser-secret",
    )

    assert result["userId"] == ("user-123")

    cookie_headers = response.headers.getlist("set-cookie")

    assert any(
        (
            auth.settings.auth_session_cookie_name in cookie
            and "session-secret" in cookie
            and "HttpOnly" in cookie
        )
        for cookie in cookie_headers
    )


@pytest.mark.anyio
async def test_verify_returns_not_recognised_for_unknown_token(
    monkeypatch,
):
    def reject_token(
        email_token,
        browser_token,
    ):
        raise (auth.ConfirmationTokenNotRecognisedError)

    monkeypatch.setattr(
        auth,
        "verify_email_token",
        reject_token,
    )

    from fastapi import HTTPException
    from fastapi import Response

    with pytest.raises(HTTPException) as exc_info:
        await auth.verify_email(
            auth.VerifyEmailRequest(token="invalid"),
            Response(),
            browser_token="browser-secret",
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "The confirmation link was not recognised"


@pytest.mark.anyio
async def test_verify_returns_did_not_work_for_browser_failure(
    monkeypatch,
):
    def reject_link(
        email_token,
        browser_token,
    ):
        raise (auth.ConfirmationLinkDidNotWorkError)

    monkeypatch.setattr(
        auth,
        "verify_email_token",
        reject_link,
    )

    from fastapi import HTTPException
    from fastapi import Response

    with pytest.raises(HTTPException) as exc_info:
        await auth.verify_email(
            auth.VerifyEmailRequest(token="email-secret"),
            Response(),
            browser_token=None,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "The confirmation link did not work"


@pytest.mark.anyio
async def test_me_returns_authenticated_user():
    result = await auth.get_authenticated_session(
        AuthenticatedUser(
            user_id="user-123",
            email=("user@justice.gov.uk"),
        )
    )

    assert result == {
        "userId": "user-123",
        "email": "user@justice.gov.uk",
    }
