import pytest

from app.cli import manage_user_access
from app.cli.manage_user_access import _build_parser


def test_parser_requires_enable_or_disable():
    parser = _build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(
            [
                "user@justice.gov.uk",
            ]
        )

    assert exc_info.value.code == 2


def test_parser_accepts_enable():
    parser = _build_parser()

    args = parser.parse_args(
        [
            "user@justice.gov.uk",
            "--enable",
        ]
    )

    assert args.email == "user@justice.gov.uk"
    assert args.enable is True
    assert args.disable is False


def test_parser_accepts_disable():
    parser = _build_parser()

    args = parser.parse_args(
        [
            "user@justice.gov.uk",
            "--disable",
        ]
    )

    assert args.email == "user@justice.gov.uk"
    assert args.enable is False
    assert args.disable is True


def test_parser_rejects_enable_and_disable_together():
    parser = _build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(
            [
                "user@justice.gov.uk",
                "--enable",
                "--disable",
            ]
        )

    assert exc_info.value.code == 2


from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.user import User


def install_user_access_test_store(
    monkeypatch,
):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
    )

    User.__table__.create(engine)

    test_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    monkeypatch.setattr(
        manage_user_access,
        "SessionLocal",
        test_session_local,
    )

    return test_session_local


def test_set_user_access_creates_enabled_user(
    monkeypatch,
):
    test_session_local = install_user_access_test_store(monkeypatch)

    result = manage_user_access.set_user_access(
        email="USER@justice.gov.uk",
        access_enabled=True,
    )

    assert result["email"] == ("user@justice.gov.uk")

    assert result["accessEnabled"] is True

    assert result["userId"]

    with test_session_local() as session:
        users = session.query(User).all()

        assert len(users) == 1

        assert users[0].email == ("user@justice.gov.uk")

        assert users[0].access_enabled is True


def test_set_user_access_enables_existing_user(
    monkeypatch,
):
    test_session_local = install_user_access_test_store(monkeypatch)

    with test_session_local() as session:
        session.add(
            User(
                user_id="user-123",
                email="user@justice.gov.uk",
                access_enabled=False,
            )
        )

        session.commit()

    result = manage_user_access.set_user_access(
        email="user@justice.gov.uk",
        access_enabled=True,
    )

    assert result == {
        "userId": "user-123",
        "email": "user@justice.gov.uk",
        "accessEnabled": True,
    }

    with test_session_local() as session:
        user = session.get(
            User,
            "user-123",
        )

        assert user is not None
        assert user.access_enabled is True


def test_set_user_access_disables_existing_user(
    monkeypatch,
):
    test_session_local = install_user_access_test_store(monkeypatch)

    with test_session_local() as session:
        session.add(
            User(
                user_id="user-123",
                email="user@justice.gov.uk",
                access_enabled=True,
            )
        )

        session.commit()

    result = manage_user_access.set_user_access(
        email="user@justice.gov.uk",
        access_enabled=False,
    )

    assert result == {
        "userId": "user-123",
        "email": "user@justice.gov.uk",
        "accessEnabled": False,
    }

    with test_session_local() as session:
        user = session.get(
            User,
            "user-123",
        )

        assert user is not None
        assert user.access_enabled is False


def test_set_user_access_reuses_existing_user_id(
    monkeypatch,
):
    test_session_local = install_user_access_test_store(monkeypatch)

    with test_session_local() as session:
        session.add(
            User(
                user_id="user-123",
                email="user@justice.gov.uk",
                access_enabled=False,
            )
        )

        session.commit()

    result = manage_user_access.set_user_access(
        email=" USER@JUSTICE.GOV.UK ",
        access_enabled=True,
    )

    assert result["userId"] == "user-123"

    with test_session_local() as session:
        users = session.query(User).all()

        assert len(users) == 1


def test_set_user_access_rejects_non_justice_email(
    monkeypatch,
):
    install_user_access_test_store(monkeypatch)

    with pytest.raises(
        ValueError,
        match="approved Justice email",
    ):
        manage_user_access.set_user_access(
            email="user@example.com",
            access_enabled=True,
        )
