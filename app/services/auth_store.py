from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.models.email_verification_token import EmailVerificationToken
from app.models.user import User
from app.models.user_session import UserSession


def get_access_enabled_user_by_email(
    email: str,
) -> dict | None:
    with SessionLocal() as session:
        user = session.execute(
            select(User).where(
                User.email == email,
                User.access_enabled.is_(True),
            )
        ).scalar_one_or_none()

        if user is None:
            return None

        return {
            "userId": user.user_id,
            "email": user.email,
        }


def create_email_verification(
    *,
    user_id: str,
    token_hash: str,
    browser_token_hash: str,
    expires_at: datetime,
) -> str:
    """
    Persist a new verification challenge.

    Only the latest unconsumed verification challenge for the user is
    retained. Both secrets are stored only as SHA-256 hashes.
    """

    verification_id = str(uuid4())

    with SessionLocal() as session:
        session.execute(
            delete(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user_id,
                EmailVerificationToken.consumed_at.is_(None),
            )
        )

        verification = EmailVerificationToken(
            verification_id=verification_id,
            user_id=user_id,
            token_hash=token_hash,
            browser_token_hash=(browser_token_hash),
            expires_at=expires_at,
        )

        session.add(verification)
        session.commit()

    return verification_id


def consume_verification_and_create_session(
    *,
    verification_token_hash: str,
    browser_token_hash: str,
    session_token_hash: str,
    session_expires_at: datetime,
    now: datetime,
) -> dict | None:
    """
    Atomically consume the verification challenge and create an
    authenticated session.

    The emailed secret and browser-bound secret must both match.
    """

    with SessionLocal() as session:
        verification = session.execute(
            select(EmailVerificationToken)
            .where(
                EmailVerificationToken.token_hash == verification_token_hash,
                EmailVerificationToken.browser_token_hash == browser_token_hash,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if verification is None:
            return None

        if verification.consumed_at is not None:
            return None

        if verification.expires_at <= now:
            return None

        user = session.execute(
            select(User)
            .where(
                User.user_id == verification.user_id,
                User.access_enabled.is_(True),
            )
            .with_for_update()
        ).scalar_one_or_none()

        if user is None:
            return None

        verification.consumed_at = now
        user.last_verified_at = now

        user_session = UserSession(
            session_id=str(uuid4()),
            user_id=user.user_id,
            session_token_hash=(session_token_hash),
            expires_at=session_expires_at,
        )

        session.add(user_session)
        session.commit()

        return {
            "userId": user.user_id,
            "email": user.email,
        }


def get_user_for_session(
    *,
    session_token_hash: str,
    now: datetime,
) -> dict | None:
    with SessionLocal() as session:
        user = session.execute(
            select(User)
            .join(
                UserSession,
                UserSession.user_id == User.user_id,
            )
            .where(
                UserSession.session_token_hash == session_token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
                User.access_enabled.is_(True),
            )
        ).scalar_one_or_none()

        if user is None:
            return None

        return {
            "userId": user.user_id,
            "email": user.email,
        }


def revoke_session(
    *,
    session_token_hash: str,
    now: datetime,
) -> bool:
    with SessionLocal() as session:
        user_session = session.execute(
            select(UserSession)
            .where(UserSession.session_token_hash == session_token_hash)
            .with_for_update()
        ).scalar_one_or_none()

        if user_session is None:
            return False

        if user_session.revoked_at is not None:
            return True

        user_session.revoked_at = now

        session.commit()

        return True
