"""API key management, on the console plane only.

Keys are created and revoked with a JWT, never with another API key. That is
deliberate containment: if a stolen key could mint more keys, revoking the
stolen one would not end the compromise.

The secret appears in exactly one response, ever. There is no endpoint that
returns it again, because there is nothing stored that could — only a SHA-256
digest and the last four characters.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.permissions import Permission
from app.core.plans import get_plan
from app.dependencies.auth import Principal, require_permission, require_verified_email
from app.dependencies.db import get_db
from app.modules.biometrics.models import AuditAction
from app.modules.biometrics.service import Actor, write_audit
from app.modules.identity import api_keys as service
from app.modules.identity.models import ApiKey, Organization

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["API keys"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadKeys = Annotated[Principal, Depends(require_permission(Permission.APIKEY_READ))]
CreateKeys = Annotated[Principal, Depends(require_permission(Permission.APIKEY_CREATE))]
RevokeKeys = Annotated[Principal, Depends(require_permission(Permission.APIKEY_REVOKE))]
VerifiedEmail = Annotated[Principal, Depends(require_verified_email)]


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["Production backend"])
    environment: str = Field(default="test", description="`test` or `live`")
    scopes: list[str] | None = Field(
        default=None,
        description=(
            "Defaults to read/write on subjects, enrollment and verification. "
            "Narrowed to what your own role can delegate - a key is never a way "
            "around RBAC."
        ),
    )
    expires_at: datetime | None = None
    ip_allowlist: str | None = Field(
        default=None,
        description="Comma-separated CIDRs. Live keys only.",
        examples=["203.0.113.0/24,198.51.100.7/32"],
    )

    @field_validator("environment")
    @classmethod
    def _known_environment(cls, value: str) -> str:
        if value not in {"test", "live"}:
            raise ValueError("environment must be 'test' or 'live'")
        return value


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    environment: str
    key_prefix: str
    last4: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    rotated_at: datetime | None
    ip_allowlist: str | None
    status: str


class ApiKeyCreated(ApiKeyResponse):
    """The only shape that ever carries the secret."""

    secret: str = Field(
        description=("Shown once. It is not stored and cannot be retrieved again - copy it now.")
    )


def _status_of(key: ApiKey) -> str:
    reason = service.is_usable(key)
    if reason is None:
        return "active"
    return "rotating" if key.rotated_at and reason == "rotation_overlap_elapsed" else reason


def _serialize(key: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=key.id,
        name=key.name,
        environment=key.environment,
        key_prefix=key.key_prefix,
        last4=key.last4,
        scopes=list(key.scopes),
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
        revoked_at=key.revoked_at,
        rotated_at=key.rotated_at,
        ip_allowlist=key.ip_allowlist,
        status=_status_of(key),
    )


@router.get(
    "/api-keys",
    response_model=list[ApiKeyResponse],
    summary="List API keys",
    description="Secrets are never returned. Only the prefix and last four characters.",
)
async def list_api_keys(principal: ReadKeys, session: DbSession) -> list[ApiKeyResponse]:
    rows = await session.scalars(
        select(ApiKey)
        .where(ApiKey.organization_id == principal.require_organization)
        .order_by(ApiKey.id.desc())
    )
    return [_serialize(row) for row in rows]


@router.post(
    "/api-keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create an API key",
    description=(
        "**The secret is returned once and never again.** Only its SHA-256 digest is "
        "stored, so there is nothing to retrieve later - if it is lost, rotate the key.\n\n"
        "Requires a verified email address: a key we cannot reach the owner of is a "
        "key nobody can be told to revoke."
    ),
)
async def create_api_key(
    body: ApiKeyCreate,
    principal: CreateKeys,
    _verified: VerifiedEmail,
    session: DbSession,
    request: Request,
) -> ApiKeyCreated:
    organization_id = principal.require_organization
    organization = await session.get(Organization, organization_id)
    plan = get_plan(organization.plan if organization else "free")

    existing = list(
        await session.scalars(
            select(ApiKey).where(
                ApiKey.organization_id == organization_id,
                ApiKey.revoked_at.is_(None),
            )
        )
    )
    # Plan limits are on *live* keys. Test keys are free because we want people
    # experimenting, and a test key cannot touch production data.
    live_count = sum(1 for key in existing if key.environment == "live")
    if body.environment == "live" and live_count >= _live_key_limit(plan.name):
        raise ConflictError(
            f"The {plan.name} plan allows {_live_key_limit(plan.name)} live keys.",
            code="key_limit_reached",
            details={"plan": plan.name, "limit": _live_key_limit(plan.name)},
        )

    if principal.role is None:
        raise ForbiddenError("A console session is required to create API keys.")

    try:
        scopes = service.normalise_scopes(body.scopes, role=principal.role)
    except ValueError as exc:
        from app.core.exceptions import BadRequestError

        raise BadRequestError(str(exc), code="invalid_scopes") from exc

    minted = service.mint(
        organization_id=organization_id,
        name=body.name,
        environment=body.environment,
        scopes=scopes,
        created_by_user_id=principal.user_id,
        expires_at=body.expires_at,
        ip_allowlist=body.ip_allowlist,
    )
    session.add(minted.api_key)
    await session.flush()

    write_audit(
        session,
        _actor(principal, request),
        AuditAction.APIKEY_CREATED,
        "api_key",
        minted.api_key.id,
        # The prefix, never the secret. An audit log that contains a working
        # credential is a credential store with extra steps.
        {"name": body.name, "environment": body.environment, "prefix": minted.api_key.key_prefix},
    )
    await session.commit()

    logger.info(
        "api_key_created",
        api_key_id=minted.api_key.id,
        environment=body.environment,
        scopes=scopes,
    )
    return ApiKeyCreated(**_serialize(minted.api_key).model_dump(), secret=minted.secret)


@router.post(
    "/api-keys/{key_id}/rotate",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Rotate an API key",
    description=(
        "Issues a replacement and keeps the old key working for **24 hours**, so you "
        "can redeploy without a window of 401s. After that the old key stops working "
        "on its own.\n\n"
        "Use `DELETE` instead when a key is known to be compromised - that takes "
        "effect on the next request, with no overlap."
    ),
)
async def rotate_api_key(
    key_id: str,
    principal: CreateKeys,
    session: DbSession,
    request: Request,
) -> ApiKeyCreated:
    old = await _get_key(session, principal.require_organization, key_id)
    if old.revoked_at is not None:
        raise ConflictError("This key is already revoked.", code="already_revoked")

    minted = service.mint(
        organization_id=old.organization_id,
        name=old.name,
        environment=old.environment,
        scopes=list(old.scopes),
        created_by_user_id=principal.user_id,
        expires_at=old.expires_at,
        ip_allowlist=old.ip_allowlist,
    )
    session.add(minted.api_key)
    await session.flush()

    old.rotated_at = datetime.now(tz=UTC)
    old.replaced_by_id = minted.api_key.id

    write_audit(
        session,
        _actor(principal, request),
        AuditAction.APIKEY_CREATED,
        "api_key",
        minted.api_key.id,
        {"rotated_from": old.id, "overlap_hours": 24},
    )
    await session.commit()

    logger.info("api_key_rotated", old=old.id, new=minted.api_key.id)
    return ApiKeyCreated(**_serialize(minted.api_key).model_dump(), secret=minted.secret)


@router.delete(
    "/api-keys/{key_id}",
    summary="Revoke an API key",
    description="Effective on the next request. No cache, no grace period.",
)
async def revoke_api_key(
    key_id: str,
    principal: RevokeKeys,
    session: DbSession,
    request: Request,
) -> dict[str, object]:
    key = await _get_key(session, principal.require_organization, key_id)
    if key.revoked_at is not None:
        return {"revoked": True, "already": True}

    key.revoked_at = datetime.now(tz=UTC)
    write_audit(
        session,
        _actor(principal, request),
        AuditAction.APIKEY_REVOKED,
        "api_key",
        key.id,
        {"prefix": key.key_prefix},
    )
    await session.commit()

    logger.info("api_key_revoked", api_key_id=key.id)
    return {"revoked": True, "already": False}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _live_key_limit(plan: str) -> int:
    return {"free": 1, "startup": 5, "growth": 20}.get(plan, 100)


async def _get_key(session: AsyncSession, organization_id: str, key_id: str) -> ApiKey:
    key = await session.get(ApiKey, key_id)
    if key is None or key.organization_id != organization_id:
        # Another tenant's key is indistinguishable from a missing one.
        raise NotFoundError(f"API key '{key_id}' was not found.")
    return key


def _actor(principal: Principal, request: Request) -> Actor:
    return Actor(
        organization_id=principal.require_organization,
        user_id=principal.user_id,
        email=principal.email,
        source="console",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
    )
