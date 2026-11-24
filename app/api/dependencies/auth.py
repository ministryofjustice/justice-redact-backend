from fastapi import (
    Cookie,
    HTTPException,
    status,
)

from app.core.settings import settings
from app.services.auth_service import (
    AuthenticatedUser,
    get_authenticated_user,
)


async def get_current_user(
    session_token: str | None = Cookie(
        default=None,
        alias=settings.auth_session_cookie_name,
    ),
) -> AuthenticatedUser:
    user = get_authenticated_user(session_token)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    return user
