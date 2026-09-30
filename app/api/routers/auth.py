from urllib.parse import quote

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Response,
    status,
)

from app.api.dependencies.auth import get_current_user
from app.core.settings import settings
from app.logging_config import logger
from app.models.auth_requests import (
    RequestVerificationRequest,
    VerifyEmailRequest,
)
from app.services.auth_service import (
    AccessNotEnabledError,
    AuthenticatedUser,
    create_verification_challenge,
    verify_email_token,
    ConfirmationLinkDidNotWorkError,
    ConfirmationTokenNotRecognisedError,
)
from app.services.notify_service import send_verification_email


router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


def _verification_link(
    token: str,
) -> str:
    """
    Put the verification token in the URL fragment.

    URL fragments are not sent to the web server, which prevents the
    verification token appearing in ingress and normal HTTP request logs.

    The frontend /confirm-email page reads the fragment and POSTs the
    token to /auth/verify.
    """

    frontend_base_url = settings.auth_frontend_base_url.rstrip("/")

    encoded_token = quote(
        token,
        safe="",
    )

    return f"{frontend_base_url}" f"/confirm-email" f"#token={encoded_token}"


@router.post("/request-verification")
async def request_verification(
    request: RequestVerificationRequest,
    response: Response,
):
    try:
        challenge = create_verification_challenge(request.email)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    verification_link = _verification_link(challenge.email_token)

    try:
        send_verification_email(
            email=challenge.email,
            verification_link=verification_link,
        )
    except Exception as exc:
        # Do not log the email address, raw token or verification URL.
        logger.exception(
            "email_verification_send_failed",
            extra={
                "event": ("email_verification_send_failed"),
                "verification_id": (challenge.verification_id),
            },
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=("The verification email could not be sent"),
        ) from exc

    response.set_cookie(
        key=settings.auth_verification_cookie_name,
        value=challenge.browser_token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        expires=challenge.expires_at,
        path="/",
    )

    logger.info(
        "email_verification_requested",
        extra={
            "event": "email_verification_requested",
            "verification_id": (challenge.verification_id),
        },
    )

    return {
        "status": "verification_email_sent",
    }


@router.post("/verify")
async def verify_email(
    request: VerifyEmailRequest,
    response: Response,
    browser_token: str | None = Cookie(
        default=None,
        alias=settings.auth_verification_cookie_name,
    ),
):
    try:
        verified_session = verify_email_token(
            request.token,
            browser_token,
        )
    except AccessNotEnabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot use Justice Redact yet",
        ) from exc
    except ConfirmationLinkDidNotWorkError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The confirmation link did not work",
        )
    except ConfirmationTokenNotRecognisedError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("The confirmation link was not recognised"),
        )

    response.set_cookie(
        key=settings.auth_session_cookie_name,
        value=verified_session.token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        expires=verified_session.expires_at,
        path="/",
    )

    response.delete_cookie(
        key=settings.auth_verification_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )

    logger.info(
        "user_authenticated",
        extra={
            "event": "user_authenticated",
            "user_id": (verified_session.user.user_id),
        },
    )

    return {
        "userId": (verified_session.user.user_id),
        "email": (verified_session.user.email),
        "expiresAt": (verified_session.expires_at.isoformat()),
    }


@router.get("/me")
async def get_authenticated_session(
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return {
        "userId": current_user.user_id,
        "email": current_user.email,
    }
