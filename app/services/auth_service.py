from __future__ import annotations

import hashlib
import secrets

from dataclasses import dataclass
from datetime import (
    datetime,
    timedelta,
    timezone,
)

from app.core.settings import settings
from app.services.auth_store import (
    consume_verification_and_create_session,
    create_email_verification,
    get_user_for_session,
)


class AccessNotEnabledError(Exception):
    pass


class ConfirmationLinkDidNotWorkError(Exception):
    pass


class ConfirmationTokenNotRecognisedError(Exception):
    pass


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    email: str


@dataclass(frozen=True)
class VerificationChallenge:
    verification_id: str
    email: str

    # Goes only into the verification email.
    email_token: str

    # Goes only into a short-lived HttpOnly browser cookie.
    browser_token: str

    expires_at: datetime


@dataclass(frozen=True)
class VerifiedSession:
    user: AuthenticatedUser
    token: str
    expires_at: datetime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_secret(
    value: str,
) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _allowed_email_domains() -> set[str]:
    return {
        domain.strip().lower().lstrip("@")
        for domain in (settings.auth_allowed_email_domains.split(","))
        if domain.strip()
    }


def normalise_and_validate_email(
    email: str,
) -> str:
    normalised_email = email.strip().lower()

    if (
        not normalised_email
        or normalised_email.count("@") != 1
        or any(character.isspace() for character in normalised_email)
    ):
        raise ValueError("Enter a valid work email address")

    local_part, domain = normalised_email.rsplit(
        "@",
        1,
    )

    if not local_part or not domain:
        raise ValueError("Enter a valid work email address")

    if domain not in (_allowed_email_domains()):
        raise ValueError("Enter an approved Justice email address")

    return normalised_email


def create_verification_challenge(
    email: str,
    *,
    now: datetime | None = None,
) -> VerificationChallenge:
    current_time = now or _utc_now()

    normalised_email = normalise_and_validate_email(email)

    raw_email_token = secrets.token_urlsafe(32)
    raw_browser_token = secrets.token_urlsafe(32)

    expires_at = current_time + timedelta(
        minutes=settings.auth_verification_token_ttl_minutes
    )

    verification_id = create_email_verification(
        email=normalised_email,
        token_hash=_hash_secret(raw_email_token),
        browser_token_hash=_hash_secret(raw_browser_token),
        expires_at=expires_at,
    )

    return VerificationChallenge(
        verification_id=verification_id,
        email=normalised_email,
        email_token=raw_email_token,
        browser_token=raw_browser_token,
        expires_at=expires_at,
    )


def verify_email_token(
    email_token: str,
    browser_token: str | None,
    *,
    now: datetime | None = None,
) -> VerifiedSession:
    if not browser_token:
        raise ConfirmationLinkDidNotWorkError

    raw_email_token = email_token.strip()

    if not raw_email_token:
        raise ConfirmationLinkDidNotWorkError

    current_time = now or _utc_now()

    raw_session_token = secrets.token_urlsafe(48)

    session_expires_at = current_time + timedelta(days=settings.auth_session_ttl_days)

    result = consume_verification_and_create_session(
        verification_token_hash=(_hash_secret(raw_email_token)),
        browser_token_hash=(_hash_secret(browser_token)),
        session_token_hash=(_hash_secret(raw_session_token)),
        session_expires_at=(session_expires_at),
        now=current_time,
    )

    if result == "token_not_recognised":
        raise ConfirmationTokenNotRecognisedError

    if result == "link_did_not_work":
        raise ConfirmationLinkDidNotWorkError

    if result == "access_not_enabled":
        raise AccessNotEnabledError

    return VerifiedSession(
        user=AuthenticatedUser(
            user_id=result["userId"],
            email=result["email"],
        ),
        token=raw_session_token,
        expires_at=session_expires_at,
    )


def get_authenticated_user(
    token: str | None,
    *,
    now: datetime | None = None,
) -> AuthenticatedUser | None:
    if not token:
        return None

    current_time = now or _utc_now()

    user = get_user_for_session(
        session_token_hash=(_hash_secret(token)),
        now=current_time,
    )

    if user is None:
        return None

    return AuthenticatedUser(
        user_id=user["userId"],
        email=user["email"],
    )
