from __future__ import annotations

import argparse
from uuid import uuid4

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.user import User
from app.services.auth_service import normalise_and_validate_email


def set_user_access(
    *,
    email: str,
    access_enabled: bool,
) -> dict:
    normalised_email = normalise_and_validate_email(
        email
    )

    with SessionLocal() as session:
        user = session.execute(
            select(User).where(
                User.email == normalised_email
            )
        ).scalar_one_or_none()

        if user is None:
            user = User(
                user_id=str(uuid4()),
                email=normalised_email,
                access_enabled=access_enabled,
            )

            session.add(user)
        else:
            user.access_enabled = access_enabled

        session.commit()
        session.refresh(user)

        return {
            "userId": user.user_id,
            "email": user.email,
            "accessEnabled": user.access_enabled,
        }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Manage Justice Redact user access"
        ),
    )

    parser.add_argument(
        "email",
        help=(
            "Justice email address to provision"
        ),
    )

    access_group = (
        parser.add_mutually_exclusive_group(
            required=True
        )
    )

    access_group.add_argument(
        "--enable",
        action="store_true",
        help="Enable Justice Redact access",
    )

    access_group.add_argument(
        "--disable",
        action="store_true",
        help="Disable Justice Redact access",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    result = set_user_access(
        email=args.email,
        access_enabled=args.enable,
    )

    state = (
        "enabled"
        if result["accessEnabled"]
        else "disabled"
    )

    print(
        f"{result['email']}: {state} "
        f"(user_id={result['userId']})"
    )


if __name__ == "__main__":
    main()
