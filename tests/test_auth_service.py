from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pytest

from app.services import auth_service


def test_normalise_and_validate_email_normalises_case_and_whitespace(
    monkeypatch,
):
    monkeypatch.setattr(
        auth_service.settings,
        "auth_allowed_email_domains",
        "justice.gov.uk",
    )

    result = auth_service.normalise_and_validate_email("  Test.User@JUSTICE.GOV.UK  ")

    assert result == ("test.user@justice.gov.uk")


def test_normalise_and_validate_email_rejects_unapproved_domain(
    monkeypatch,
):
    monkeypatch.setattr(
        auth_service.settings,
        "auth_allowed_email_domains",
        "justice.gov.uk",
    )

    with pytest.raises(
        ValueError,
        match="approved Justice email",
    ):
        (auth_service.normalise_and_validate_email("test@example.com"))


def test_domain_check_does_not_use_unsafe_suffix_matching(
    monkeypatch,
):
    monkeypatch.setattr(
        auth_service.settings,
        "auth_allowed_email_domains",
        "justice.gov.uk",
    )

    with pytest.raises(ValueError):
        (auth_service.normalise_and_validate_email("test@notjustice.gov.uk"))


def test_create_verification_challenge_rejects_user_without_access(
    monkeypatch,
):
    monkeypatch.setattr(
        auth_service.settings,
        "auth_allowed_email_domains",
        "justice.gov.uk",
    )

    monkeypatch.setattr(
        auth_service,
        "get_access_enabled_user_by_email",
        lambda email: None,
    )

    with pytest.raises(auth_service.AccessNotEnabledError):
        (auth_service.create_verification_challenge("user@justice.gov.uk"))


def test_create_verification_challenge_persists_only_hashes(
    monkeypatch,
):
    monkeypatch.setattr(
        auth_service.settings,
        "auth_allowed_email_domains",
        "justice.gov.uk",
    )

    monkeypatch.setattr(
        auth_service,
        "get_access_enabled_user_by_email",
        lambda email: {
            "userId": "user-123",
            "email": email,
        },
    )

    generated_tokens = iter(
        [
            "raw-email-token",
            "raw-browser-token",
        ]
    )

    monkeypatch.setattr(
        auth_service.secrets,
        "token_urlsafe",
        lambda _: next(generated_tokens),
    )

    captured = {}

    def fake_create_email_verification(
        *,
        user_id,
        token_hash,
        browser_token_hash,
        expires_at,
    ):
        captured["user_id"] = user_id
        captured["token_hash"] = token_hash
        captured["browser_token_hash"] = browser_token_hash

        return "verification-123"

    monkeypatch.setattr(
        auth_service,
        "create_email_verification",
        fake_create_email_verification,
    )

    now = datetime(
        2026,
        9,
        29,
        12,
        0,
        tzinfo=timezone.utc,
    )

    result = auth_service.create_verification_challenge(
        "USER@justice.gov.uk",
        now=now,
    )

    assert result.verification_id == "verification-123"

    assert result.email == "user@justice.gov.uk"

    assert result.email_token == "raw-email-token"

    assert result.browser_token == "raw-browser-token"

    assert captured["token_hash"] != "raw-email-token"

    assert captured["browser_token_hash"] != "raw-browser-token"

    assert len(captured["token_hash"]) == 64

    assert len(captured["browser_token_hash"]) == 64


def test_verified_session_lasts_seven_days(
    monkeypatch,
):
    monkeypatch.setattr(
        auth_service.settings,
        "auth_session_ttl_days",
        7,
    )

    monkeypatch.setattr(
        auth_service.secrets,
        "token_urlsafe",
        lambda _: "raw-session-token",
    )

    captured = {}

    def fake_consume(
        *,
        verification_token_hash,
        browser_token_hash,
        session_token_hash,
        session_expires_at,
        now,
    ):
        captured["session_expires_at"] = session_expires_at

        return {
            "userId": "user-123",
            "email": "user@justice.gov.uk",
        }

    monkeypatch.setattr(
        auth_service,
        "consume_verification_and_create_session",
        fake_consume,
    )

    now = datetime(
        2026,
        9,
        29,
        12,
        0,
        tzinfo=timezone.utc,
    )

    result = auth_service.verify_email_token(
        "raw-email-token",
        "raw-browser-token",
        now=now,
    )

    assert result is not None

    assert result.expires_at == now + timedelta(days=7)

    assert captured["session_expires_at"] == now + timedelta(days=7)


def test_verify_email_token_requires_browser_token():
    with pytest.raises(auth_service.ConfirmationLinkDidNotWorkError):
        auth_service.verify_email_token(
            "raw-email-token",
            None,
        )


def test_verify_email_token_rejects_unrecognised_token(
    monkeypatch,
):
    monkeypatch.setattr(
        auth_service,
        "consume_verification_and_create_session",
        lambda **kwargs: "token_not_recognised",
    )

    with pytest.raises(auth_service.ConfirmationTokenNotRecognisedError):
        auth_service.verify_email_token(
            "unknown-email-token",
            "browser-token",
        )


def test_verify_email_token_rejects_unusable_link(
    monkeypatch,
):
    monkeypatch.setattr(
        auth_service,
        "consume_verification_and_create_session",
        lambda **kwargs: "link_did_not_work",
    )

    with pytest.raises(auth_service.ConfirmationLinkDidNotWorkError):
        auth_service.verify_email_token(
            "email-token",
            "wrong-browser-token",
        )
