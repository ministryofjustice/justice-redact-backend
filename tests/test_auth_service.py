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


def test_create_verification_challenge_persists_only_hashes(
    monkeypatch,
):
    monkeypatch.setattr(
        auth_service.settings,
        "auth_allowed_email_domains",
        "justice.gov.uk",
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
        email,
        token_hash,
        browser_token_hash,
        expires_at,
    ):
        captured["email"] = email
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

    assert captured["email"] == "user@justice.gov.uk"

    assert captured["token_hash"] != "raw-email-token"

    assert captured["browser_token_hash"] != "raw-browser-token"

    assert len(captured["token_hash"]) == 64

    assert len(captured["browser_token_hash"]) == 64


def test_verification_challenge_expires_at_next_uk_midnight(
    monkeypatch,
):
    monkeypatch.setattr(
        auth_service.settings,
        "auth_allowed_email_domains",
        "justice.gov.uk",
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
        email,
        token_hash,
        browser_token_hash,
        expires_at,
    ):
        captured["expires_at"] = expires_at

        return "verification-123"

    monkeypatch.setattr(
        auth_service,
        "create_email_verification",
        fake_create_email_verification,
    )

    # Wednesday 30 September 2026 at
    # 13:00 BST / 12:00 UTC.
    # The link should expire at 00:00 BST,
    # which is 23:00 UTC.
    now = datetime(
        2026,
        9,
        30,
        12,
        0,
        tzinfo=timezone.utc,
    )

    expected_expiry = datetime(
        2026,
        9,
        30,
        23,
        0,
        tzinfo=timezone.utc,
    )

    result = auth_service.create_verification_challenge(
        "user@justice.gov.uk",
        now=now,
    )

    assert result.expires_at == expected_expiry

    assert captured["expires_at"] == expected_expiry


def test_verified_session_expires_at_next_monday_midnight(
    monkeypatch,
):
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

    # Wednesday 30 September 2026.
    # The UK is on BST, so Monday 5 October
    # 00:00 Europe/London is Sunday 4 October
    # 23:00 UTC.
    now = datetime(
        2026,
        9,
        30,
        12,
        0,
        tzinfo=timezone.utc,
    )

    expected_expiry = datetime(
        2026,
        10,
        4,
        23,
        0,
        tzinfo=timezone.utc,
    )

    result = auth_service.verify_email_token(
        "raw-email-token",
        "raw-browser-token",
        now=now,
    )

    assert result.expires_at == expected_expiry

    assert captured["session_expires_at"] == expected_expiry


def test_verification_challenge_expiry_handles_gmt(
    monkeypatch,
):
    monkeypatch.setattr(
        auth_service.settings,
        "auth_allowed_email_domains",
        "justice.gov.uk",
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
        email,
        token_hash,
        browser_token_hash,
        expires_at,
    ):
        captured["expires_at"] = expires_at

        return "verification-123"

    monkeypatch.setattr(
        auth_service,
        "create_email_verification",
        fake_create_email_verification,
    )

    # November is GMT, so UK midnight is also 00:00 UTC.
    now = datetime(
        2026,
        11,
        10,
        12,
        0,
        tzinfo=timezone.utc,
    )

    expected_expiry = datetime(
        2026,
        11,
        11,
        0,
        0,
        tzinfo=timezone.utc,
    )

    result = auth_service.create_verification_challenge(
        "user@justice.gov.uk",
        now=now,
    )

    assert result.expires_at == expected_expiry
    assert captured["expires_at"] == expected_expiry


def test_verified_session_expiry_handles_gmt(
    monkeypatch,
):
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

    # Friday 30 October 2026 is GMT.
    # Next Monday midnight is 2 November 00:00 UTC.
    now = datetime(
        2026,
        10,
        30,
        12,
        0,
        tzinfo=timezone.utc,
    )

    expected_expiry = datetime(
        2026,
        11,
        2,
        0,
        0,
        tzinfo=timezone.utc,
    )

    result = auth_service.verify_email_token(
        "raw-email-token",
        "raw-browser-token",
        now=now,
    )

    assert result.expires_at == expected_expiry
    assert captured["session_expires_at"] == expected_expiry


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


def test_verify_email_token_rejects_user_without_access(
    monkeypatch,
):
    monkeypatch.setattr(
        auth_service,
        "consume_verification_and_create_session",
        lambda **kwargs: "access_not_enabled",
    )

    with pytest.raises(auth_service.AccessNotEnabledError):
        auth_service.verify_email_token(
            "email-token",
            "browser-token",
        )
