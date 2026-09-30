from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.email_verification_token import (
    EmailVerificationToken,
)
from app.models.user import User
from app.models.user_session import UserSession
from app.services import auth_store


NOW = datetime(
    2026,
    9,
    29,
    12,
    0,
    tzinfo=timezone.utc,
)


def install_auth_store_test_database(
    monkeypatch,
):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
    )

    User.__table__.create(engine)
    EmailVerificationToken.__table__.create(engine)
    UserSession.__table__.create(engine)

    test_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    monkeypatch.setattr(
        auth_store,
        "SessionLocal",
        test_session_local,
    )

    return test_session_local


def add_verification(
    test_session_local,
    *,
    email: str = "user@justice.gov.uk",
    token_hash: str = "email-token-hash",
    browser_token_hash: str = "browser-token-hash",
    expires_at: datetime | None = None,
    consumed_at: datetime | None = None,
    create_user: bool = True,
    access_enabled: bool = True,
):
    with test_session_local() as session:
        if create_user:
            session.add(
                User(
                    user_id="user-123",
                    email=email,
                    access_enabled=access_enabled,
                )
            )

        session.add(
            EmailVerificationToken(
                verification_id="verification-123",
                email=email,
                token_hash=token_hash,
                browser_token_hash=browser_token_hash,
                expires_at=(expires_at or NOW + timedelta(minutes=30)),
                consumed_at=consumed_at,
            )
        )

        session.commit()


def consume(
    **overrides,
):
    values = {
        "verification_token_hash": "email-token-hash",
        "browser_token_hash": "browser-token-hash",
        "session_token_hash": "session-token-hash",
        "session_expires_at": NOW + timedelta(days=7),
        "now": NOW,
    }

    values.update(overrides)

    return auth_store.consume_verification_and_create_session(**values)


def test_create_email_verification_does_not_require_user(
    monkeypatch,
):
    test_session_local = install_auth_store_test_database(monkeypatch)

    verification_id = auth_store.create_email_verification(
        email="not-in-cohort@justice.gov.uk",
        token_hash="email-token-hash",
        browser_token_hash="browser-token-hash",
        expires_at=NOW + timedelta(minutes=30),
    )

    with test_session_local() as session:
        verification = session.get(
            EmailVerificationToken,
            verification_id,
        )

        assert verification is not None
        assert verification.email == "not-in-cohort@justice.gov.uk"
        assert verification.token_hash == "email-token-hash"
        assert verification.browser_token_hash == "browser-token-hash"

        assert session.query(User).count() == 0


def test_consume_verification_creates_session(
    monkeypatch,
):
    test_session_local = install_auth_store_test_database(monkeypatch)

    add_verification(test_session_local)

    result = consume()

    assert result == {
        "userId": "user-123",
        "email": "user@justice.gov.uk",
    }

    with test_session_local() as session:
        verification = session.get(
            EmailVerificationToken,
            "verification-123",
        )

        assert verification is not None
        assert verification.consumed_at is not None

        sessions = session.query(UserSession).all()

        assert len(sessions) == 1

        assert sessions[0].user_id == "user-123"

        assert sessions[0].session_token_hash == "session-token-hash"


def test_consume_verification_rejects_unknown_token(
    monkeypatch,
):
    test_session_local = install_auth_store_test_database(monkeypatch)

    add_verification(test_session_local)

    result = consume(verification_token_hash=("unknown-token-hash"))

    assert result == "token_not_recognised"

    with test_session_local() as session:
        assert session.query(UserSession).count() == 0


def test_consume_verification_rejects_wrong_browser(
    monkeypatch,
):
    test_session_local = install_auth_store_test_database(monkeypatch)

    add_verification(test_session_local)

    result = consume(browser_token_hash=("different-browser-hash"))

    assert result == "link_did_not_work"

    with test_session_local() as session:
        verification = session.get(
            EmailVerificationToken,
            "verification-123",
        )

        assert verification is not None
        assert verification.consumed_at is None

        assert session.query(UserSession).count() == 0


def test_consume_verification_rejects_expired_link(
    monkeypatch,
):
    test_session_local = install_auth_store_test_database(monkeypatch)

    add_verification(
        test_session_local,
        expires_at=(NOW - timedelta(seconds=1)),
    )

    result = consume()

    assert result == "link_did_not_work"

    with test_session_local() as session:
        assert session.query(UserSession).count() == 0


def test_consume_verification_rejects_consumed_link(
    monkeypatch,
):
    test_session_local = install_auth_store_test_database(monkeypatch)

    add_verification(
        test_session_local,
        consumed_at=(NOW - timedelta(minutes=1)),
    )

    result = consume()

    assert result == "link_did_not_work"

    with test_session_local() as session:
        assert session.query(UserSession).count() == 0


def test_consume_verification_rejects_disabled_user(
    monkeypatch,
):
    test_session_local = install_auth_store_test_database(monkeypatch)

    add_verification(
        test_session_local,
        access_enabled=False,
    )

    result = consume()

    assert result == "access_not_enabled"

    with test_session_local() as session:
        verification = session.get(
            EmailVerificationToken,
            "verification-123",
        )

        assert verification is not None
        assert verification.consumed_at is not None

        assert session.query(UserSession).count() == 0

    with test_session_local() as session:
        assert session.query(UserSession).count() == 0


def test_consume_verification_rejects_user_not_in_cohort(
    monkeypatch,
):
    test_session_local = install_auth_store_test_database(monkeypatch)

    add_verification(
        test_session_local,
        create_user=False,
    )

    result = consume()

    assert result == "access_not_enabled"

    with test_session_local() as session:
        verification = session.get(
            EmailVerificationToken,
            "verification-123",
        )

        assert verification is not None
        assert verification.consumed_at is not None

        assert session.query(UserSession).count() == 0
