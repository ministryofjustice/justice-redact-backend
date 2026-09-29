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
        captured["link"] = (
            verification_link
        )

        return "notification-123"

    monkeypatch.setattr(
        auth,
        "send_verification_email",
        fake_send,
    )

    from fastapi import Response

    response = Response()

    result = await auth.request_verification(
        auth.RequestVerificationRequest(
            email="user@justice.gov.uk"
        ),
        response,
    )

    assert result == {
        "status": (
            "verification_email_sent"
        ),
    }

    assert captured["email"] == (
        "user@justice.gov.uk"
    )

    assert (
        "#token=email-secret"
        in captured["link"]
    )

    cookie = response.headers[
        "set-cookie"
    ]

    assert (
        auth.settings
        .auth_verification_cookie_name
        in cookie
    )

    assert "browser-secret" in cookie
    assert "HttpOnly" in cookie


@pytest.mark.anyio
async def test_request_verification_rejects_user_without_access(
    monkeypatch,
):
    def reject(email):
        raise AccessNotEnabledError()

    monkeypatch.setattr(
        auth,
        "create_verification_challenge",
        reject,
    )

    from fastapi import HTTPException
    from fastapi import Response

    with pytest.raises(
        HTTPException
    ) as exc_info:
        await auth.request_verification(
            auth.RequestVerificationRequest(
                email="user@justice.gov.uk"
            ),
            Response(),
        )

    assert (
        exc_info.value.status_code
        == 403
    )


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
        lambda email_token, browser_token: (
            verified
        ),
    )

    from fastapi import Response

    response = Response()

    result = await auth.verify_email(
        auth.VerifyEmailRequest(
            token="email-secret"
        ),
        response,
        browser_token="browser-secret",
    )

    assert result["userId"] == (
        "user-123"
    )

    cookie_headers = response.headers.getlist(
        "set-cookie"
    )

    assert any(
        (
            auth.settings
            .auth_session_cookie_name
            in cookie
            and "session-secret" in cookie
            and "HttpOnly" in cookie
        )
        for cookie in cookie_headers
    )


@pytest.mark.anyio
async def test_verify_rejects_invalid_challenge(
    monkeypatch,
):
    monkeypatch.setattr(
        auth,
        "verify_email_token",
        lambda email_token, browser_token: (
            None
        ),
    )

    from fastapi import HTTPException
    from fastapi import Response

    with pytest.raises(
        HTTPException
    ) as exc_info:
        await auth.verify_email(
            auth.VerifyEmailRequest(
                token="invalid"
            ),
            Response(),
            browser_token="browser-secret",
        )

    assert (
        exc_info.value.status_code
        == 400
    )


@pytest.mark.anyio
async def test_me_returns_authenticated_user():
    result = (
        await auth
        .get_authenticated_session(
            AuthenticatedUser(
                user_id="user-123",
                email=(
                    "user@justice.gov.uk"
                ),
            )
        )
    )

    assert result == {
        "userId": "user-123",
        "email": "user@justice.gov.uk",
    }


@pytest.mark.anyio
async def test_logout_revokes_session_and_clears_cookie(
    monkeypatch,
):
    captured = {}

    monkeypatch.setattr(
        auth,
        "revoke_authenticated_session",
        lambda token: captured.update(
            token=token
        )
        or True,
    )

    from fastapi import Response

    response = Response()

    result = await auth.logout(
        response,
        session_token="session-secret",
    )

    assert captured["token"] == (
        "session-secret"
    )

    assert result == {
        "status": "logged_out",
    }
