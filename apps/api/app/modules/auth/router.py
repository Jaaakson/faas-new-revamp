"""Console authentication endpoints.

Mounted under `/v1/console/auth`. Routers here only parse, delegate, and
serialize — every rule lives in `AuthService`.
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.dependencies.auth import CurrentPrincipal
from app.dependencies.db import get_db
from app.modules.auth.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SessionResponse,
    SwitchOrganizationRequest,
    UserProfile,
    VerifyEmailRequest,
)
from app.modules.auth.service import RESET_SENT_MESSAGE, AuthService
from app.modules.identity.models import User

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


@router.post(
    "/register",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    description=(
        "Registers a user and, unless an invitation token is supplied, creates a "
        "personal organization with the user as its Owner. Returns a session so the "
        "caller lands signed in rather than being bounced to a login form."
    ),
    responses={
        400: {"description": "Weak password or invalid invitation"},
        409: {"description": "An account with this email already exists"},
    },
)
async def register(
    payload: RegisterRequest, request: Request, session: DbSession
) -> SessionResponse:
    service = AuthService(session)
    user, verification_token = await service.register(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        organization_name=payload.organization_name,
        invitation_token=payload.invitation_token,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )

    # Transactional email lands with the delivery work; until then the token is
    # logged at debug level so local development can complete the flow. It is
    # never returned in the response, which would defeat verification entirely.
    logger.debug("email_verification_token_issued", user_id=user.id)
    _ = verification_token

    return await service.login(
        email=payload.email,
        password=payload.password,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )


@router.post(
    "/login",
    response_model=SessionResponse,
    summary="Sign in",
    description=(
        "Returns a short-lived access token and a rotating refresh token. The refresh "
        "token is intended for an httpOnly cookie set by the BFF, never for browser "
        "storage."
    ),
    responses={
        401: {"description": "Incorrect email or password"},
        403: {"description": "Account temporarily locked"},
    },
)
async def login(payload: LoginRequest, request: Request, session: DbSession) -> SessionResponse:
    return await AuthService(session).login(
        email=payload.email,
        password=payload.password,
        organization_id=payload.organization_id,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )


@router.post(
    "/refresh",
    response_model=SessionResponse,
    summary="Rotate the session",
    description=(
        "Exchanges a refresh token for a new pair and revokes the old one. Presenting "
        "an already-used token revokes the entire family and forces re-authentication."
    ),
    responses={401: {"description": "Invalid, expired, or reused refresh token"}},
)
async def refresh(payload: RefreshRequest, request: Request, session: DbSession) -> SessionResponse:
    return await AuthService(session).refresh(
        refresh_token=payload.refresh_token,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )


@router.post(
    "/switch-organization",
    response_model=SessionResponse,
    summary="Re-issue the session against a different organization",
    description=(
        "The active tenant lives in the access token, not in a request parameter, so "
        "switching means minting a new session. Membership is verified server-side and "
        "the refresh token rotates, keeping exactly one live lineage."
    ),
    responses={
        401: {"description": "Invalid or expired refresh token"},
        404: {"description": "Not a member of that organization"},
    },
)
async def switch_organization(
    payload: SwitchOrganizationRequest, request: Request, session: DbSession
) -> SessionResponse:
    return await AuthService(session).switch_organization(
        refresh_token=payload.refresh_token,
        organization_id=payload.organization_id,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Sign out",
    description="Revokes the current token family, or every session for the user.",
)
async def logout(
    payload: LogoutRequest,
    principal: CurrentPrincipal,
    request: Request,
    session: DbSession,
) -> MessageResponse:
    await AuthService(session).logout(
        user_id=principal.user_id,
        refresh_token=payload.refresh_token,
        all_sessions=payload.all_sessions,
        ip=_client_ip(request),
    )
    return MessageResponse(message="Signed out.")


@router.post(
    "/verify-email",
    response_model=UserProfile,
    summary="Verify an email address",
    responses={400: {"description": "Invalid or expired verification link"}},
)
async def verify_email(
    payload: VerifyEmailRequest, request: Request, session: DbSession
) -> UserProfile:
    user = await AuthService(session).verify_email(token=payload.token, ip=_client_ip(request))
    return UserProfile(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        email_verified=user.is_email_verified,
        created_at=user.created_at,
    )


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request a password reset",
    description=(
        "Always returns the same response whether or not the address is registered. "
        "Varying the status, message, or timing would make this an account-enumeration "
        "oracle."
    ),
)
async def forgot_password(
    payload: ForgotPasswordRequest, request: Request, session: DbSession
) -> MessageResponse:
    token = await AuthService(session).request_password_reset(
        email=payload.email, ip=_client_ip(request)
    )
    if token:
        logger.debug("password_reset_token_issued")
    return MessageResponse(message=RESET_SENT_MESSAGE)


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Set a new password with a reset token",
    description="Single-use. Succeeding also revokes every active session for the user.",
    responses={400: {"description": "Invalid or expired token, or weak password"}},
)
async def reset_password(
    payload: ResetPasswordRequest, request: Request, session: DbSession
) -> MessageResponse:
    await AuthService(session).reset_password(
        token=payload.token, new_password=payload.password, ip=_client_ip(request)
    )
    return MessageResponse(message="Your password has been reset. Please sign in.")


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change your password",
    responses={401: {"description": "Current password is incorrect"}},
)
async def change_password(
    payload: ChangePasswordRequest,
    principal: CurrentPrincipal,
    session: DbSession,
) -> MessageResponse:
    user = await session.get(User, principal.user_id)
    if user is None:  # pragma: no cover - principal resolution already loaded it
        raise RuntimeError("authenticated principal without a user row")

    await AuthService(session).change_password(
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return MessageResponse(message="Your password has been changed.")


@router.get(
    "/me",
    response_model=MeResponse,
    summary="The current user, their organizations, and permissions",
    description=(
        "The console calls this on load to render navigation and decide which controls "
        "to enable. Those checks are UX — the server enforces permissions independently."
    ),
)
async def me(principal: CurrentPrincipal, session: DbSession) -> MeResponse:
    user, organizations, permissions = await AuthService(session).describe_user(
        user_id=principal.user_id,
        active_organization_id=principal.organization_id,
    )
    return MeResponse(
        user=UserProfile(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            avatar_url=user.avatar_url,
            email_verified=user.is_email_verified,
            created_at=user.created_at,
        ),
        organizations=organizations,
        active_organization_id=principal.organization_id,
        permissions=permissions,
    )


@router.get(
    "/session-policy",
    summary="Token lifetimes the client should assume",
    description=(
        "Lets the BFF schedule a silent refresh instead of hard-coding a lifetime that "
        "would silently disagree with the server after a config change."
    ),
)
async def session_policy() -> dict[str, int]:
    return {
        "access_token_expire_minutes": settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        "refresh_token_expire_days": settings.REFRESH_TOKEN_EXPIRE_DAYS,
    }
