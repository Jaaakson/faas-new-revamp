"""Authentication and authorization dependencies.

`Principal` is the resolved caller. Phase 3 produces it only from a console JWT;
Phase 7 adds an API-key variant behind the same type, so routers and services
never learn which plane a request arrived on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthenticatedError
from app.core.permissions import Permission, Role, has_permission
from app.core.security import TokenError, decode_access_token
from app.core.tenancy import set_tenant
from app.dependencies.db import get_db
from app.modules.identity.models import ApiKey, Membership, User

# auto_error=False so a missing header produces our own error envelope rather
# than Starlette's bare {"detail": ...}.
logger = structlog.get_logger(__name__)

_bearer = HTTPBearer(auto_error=False, description="Console access token")


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller and its active tenant.

    One type for both authentication planes. A console request carries a `role`;
    an API-key request carries `scopes`. Everything downstream — routers,
    services, repositories — asks `can()` and never learns which plane the
    request arrived on, which is what makes "the API path produces the same
    result as the console path" structural rather than something to test for.
    """

    user_id: str
    email: str
    organization_id: str | None
    role: Role | None
    is_email_verified: bool
    # Present only on the API-key plane. `None` means "ask the role"; an empty
    # set means "a key that may do nothing", and those are different states.
    scopes: frozenset[str] | None = None
    api_key_id: str | None = None

    @property
    def is_api_key(self) -> bool:
        return self.api_key_id is not None

    def can(self, permission: Permission | str) -> bool:
        """Scopes win when present.

        A key's scopes are already the intersection of what its creator could
        delegate and what the public plane allows, so they are the narrower
        answer and the correct one. Falling back to the role here would let a
        key inherit permissions it was deliberately not granted.
        """
        wanted = permission.value if isinstance(permission, Permission) else permission
        if self.scopes is not None:
            return wanted in self.scopes
        return self.role is not None and has_permission(self.role, permission)

    @property
    def require_organization(self) -> str:
        """The active org, or a clear error instead of a None-shaped crash."""
        if not self.organization_id:
            raise ForbiddenError(
                "This request requires an active organization.",
                code="no_active_organization",
            )
        return self.organization_id


async def get_current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Principal:
    """Resolve the caller from the bearer token.

    The token carries `org` and `role`, but membership is re-read here. A token
    issued before a role change or a removal would otherwise stay valid for its
    full lifetime — acceptable for cheap reads, not for authorization. One
    indexed lookup per request buys correctness.
    """
    if credentials is None or not credentials.credentials:
        raise UnauthenticatedError("An access token is required.")

    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise UnauthenticatedError(str(exc)) from exc

    user_id = str(payload["sub"])
    organization_id = payload.get("org")

    user = await session.get(User, user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise UnauthenticatedError("This account is no longer active.")

    role: Role | None = None
    if organization_id:
        result = await session.execute(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.organization_id == organization_id,
                Membership.status == "active",
            )
        )
        membership = result.scalar_one_or_none()
        if membership is None:
            # Revoked mid-token-lifetime. Treat as unauthenticated for this org
            # rather than forbidden — the caller should re-authenticate and pick
            # an organization they still belong to.
            raise UnauthenticatedError("You no longer have access to this organization.")
        role = Role(membership.role.slug)

    principal = Principal(
        user_id=user.id,
        email=user.email,
        organization_id=organization_id,
        role=role,
        is_email_verified=user.is_email_verified,
    )
    # Stashed for the access log and audit trail.
    request.state.principal = principal
    # Bind the transaction to this tenant so Postgres RLS applies. Done here
    # rather than in `get_db`, because the tenant is not known until the
    # membership lookup above has run.
    await set_tenant(session, organization_id)
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def require_permission(permission: Permission):  # type: ignore[no-untyped-def]
    """Dependency factory enforcing a single permission.

    The frontend also hides unpermitted controls, but that is UX. This is the
    security boundary, and it is the only one that counts.
    """

    async def dependency(principal: CurrentPrincipal) -> Principal:
        # Raises when the session has no active organization. Assigned rather
        # than left bare so the intent is a check, not a stray expression.
        _ = principal.require_organization
        if not principal.can(permission):
            raise ForbiddenError(
                "You do not have permission to perform this action.",
                details={
                    "required_permission": permission.value,
                    "your_role": principal.role.value if principal.role else None,
                },
            )
        return principal

    return dependency


async def require_verified_email(principal: CurrentPrincipal) -> Principal:
    """Gate actions that must not happen on an unverified account.

    API key creation is the important one: an unverified address means we cannot
    reach the owner of a key that later needs revoking.
    """
    if not principal.is_email_verified:
        raise ForbiddenError(
            "Verify your email address before performing this action.",
            code="email_not_verified",
        )
    return principal


# ── The API-key plane ─────────────────────────────────────────────────────────

_api_key_bearer = HTTPBearer(auto_error=False, description="API key (fvas_live_… / fvas_test_…)")


async def get_api_key_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_api_key_bearer)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Principal:
    """Resolve the caller from an API key.

    Every rejection returns the same message. Distinguishing "no such key" from
    "revoked" from "expired" would tell an attacker which of their guesses was a
    real key, and the reason is logged for the customer's benefit instead.
    """
    from app.modules.identity import api_keys as api_key_service

    if credentials is None or not credentials.credentials:
        raise UnauthenticatedError(
            "An API key is required. Send it as `Authorization: Bearer fvas_live_…`."
        )

    address = request.client.host if request.client else None
    try:
        key = await api_key_service.verify(session, credentials.credentials, ip_address=address)
    except api_key_service.ApiKeyError as exc:
        logger.info("api_key_rejected", reason=exc.reason, client_ip=address)
        raise UnauthenticatedError("The API key is invalid, revoked, or expired.") from exc

    principal = Principal(
        # A key is not a person. `user_id` stays empty rather than borrowing the
        # creator's, so an audit entry cannot imply a human took an action a
        # machine took.
        user_id="",
        email=f"key:{key.key_prefix}",
        organization_id=key.organization_id,
        role=None,
        is_email_verified=True,
        scopes=frozenset(key.scopes),
        api_key_id=key.id,
    )
    request.state.principal = principal
    request.state.api_key = key
    await set_tenant(session, key.organization_id)

    # Coalesced through Redis: at most one UPDATE per key per minute. Writing
    # this row on every call would put lock contention on the busiest path in
    # the product for a field nobody reads in real time.
    await _touch_api_key(session, key, address)

    return principal


async def _touch_api_key(session: AsyncSession, key: ApiKey, address: str | None) -> None:
    """Record `last_used_at`, at most once a minute per key."""
    from redis.exceptions import RedisError

    from app.core.redis import get_redis

    try:
        claimed = await get_redis().set(f"apikey:touched:{key.id}", "1", ex=60, nx=True)
    except RedisError:
        # Redis down: skip the write entirely rather than doing it on every
        # request. `last_used_at` is a convenience for the customer, and going
        # uncoalesced under an outage is exactly when it would hurt most.
        return

    if not claimed:
        return

    key.last_used_at = datetime.now(tz=UTC)
    key.last_used_ip = address
    await session.commit()


ApiKeyPrincipal = Annotated[Principal, Depends(get_api_key_principal)]


def require_scope(permission: Permission):  # type: ignore[no-untyped-def]
    """Enforce a scope on the public API.

    Deliberately separate from `require_permission` only in which dependency
    resolves the principal. The check itself is the same `can()` call, so the
    two planes cannot drift apart in what they allow.
    """

    async def dependency(principal: ApiKeyPrincipal) -> Principal:
        _ = principal.require_organization
        if not principal.can(permission):
            raise ForbiddenError(
                "This API key does not carry the required scope.",
                details={
                    "required_scope": permission.value,
                    "key_scopes": sorted(principal.scopes or ()),
                },
            )
        return principal

    return dependency
