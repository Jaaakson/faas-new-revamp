"""Webhook management endpoints.

The secret is returned **once**, at creation and at rotation, and never again.
Listing an endpoint shows a masked hint instead. A secret readable from a list
endpoint is a secret that lives in every browser cache and log that ever touched
the console.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.dependencies.auth import Principal, require_permission
from app.dependencies.db import get_db
from app.modules.biometrics.models import WEBHOOK_EVENTS, WebhookDelivery, WebhookEndpoint
from app.modules.webhooks.service import WebhookService

router = APIRouter(tags=["Webhooks"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
ManageWebhooks = Annotated[Principal, Depends(require_permission(Permission.WEBHOOK_MANAGE))]


class WebhookCreate(BaseModel):
    url: str = Field(description="An https URL. Public hosts only.")
    events: list[str] = Field(
        min_length=1,
        description=f"Any of: {', '.join(WEBHOOK_EVENTS)}",
    )
    description: str | None = Field(default=None, max_length=200)


class WebhookUpdate(BaseModel):
    url: str | None = None
    events: list[str] | None = None
    description: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None


class WebhookResponse(BaseModel):
    id: str
    url: str
    description: str | None
    events: list[str]
    is_active: bool
    failure_count: int
    disabled_at: datetime | None
    last_delivery_at: datetime | None
    created_at: datetime
    # Enough to tell two endpoints apart in a list, not enough to forge with.
    secret_hint: str


class WebhookWithSecret(WebhookResponse):
    """Returned only at creation and rotation."""

    secret: str = Field(description="Shown once. Store it now - it cannot be retrieved later.")


class DeliveryResponse(BaseModel):
    id: str
    endpoint_id: str
    event_type: str
    event_id: str
    status: str
    attempt_count: int
    response_status: int | None
    error: str | None
    next_retry_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime


@router.get("/webhooks", response_model=list[WebhookResponse], summary="List webhook endpoints")
async def list_webhooks(principal: ManageWebhooks, session: DbSession) -> list[WebhookResponse]:
    service = WebhookService(session, principal.require_organization)
    return [_serialize(endpoint) for endpoint in await service.list_endpoints()]


@router.post(
    "/webhooks",
    response_model=WebhookWithSecret,
    status_code=status.HTTP_201_CREATED,
    summary="Create a webhook endpoint",
    description=(
        "The signing secret is returned **once**. Verify every delivery with it:\n\n"
        "`Fvas-Signature: t=<unix>,v1=<hex>` is HMAC-SHA256 over `{t}.{raw body}`. "
        "Reject anything more than five minutes old, and compare in constant time.\n\n"
        "Delivery is at-least-once - dedupe on `Fvas-Event-Id`."
    ),
)
async def create_webhook(
    body: WebhookCreate, principal: ManageWebhooks, session: DbSession
) -> WebhookWithSecret:
    service = WebhookService(session, principal.require_organization)
    endpoint = await service.create_endpoint(
        url=body.url, events=body.events, description=body.description
    )
    return WebhookWithSecret(**_serialize(endpoint).model_dump(), secret=endpoint.secret)


@router.patch("/webhooks/{endpoint_id}", response_model=WebhookResponse, summary="Update")
async def update_webhook(
    endpoint_id: str, body: WebhookUpdate, principal: ManageWebhooks, session: DbSession
) -> WebhookResponse:
    service = WebhookService(session, principal.require_organization)
    endpoint = await service.update_endpoint(endpoint_id, **body.model_dump(exclude_unset=True))
    return _serialize(endpoint)


@router.delete("/webhooks/{endpoint_id}", summary="Delete a webhook endpoint")
async def delete_webhook(
    endpoint_id: str, principal: ManageWebhooks, session: DbSession
) -> dict[str, bool]:
    service = WebhookService(session, principal.require_organization)
    await service.delete_endpoint(endpoint_id)
    return {"deleted": True}


@router.post(
    "/webhooks/{endpoint_id}/rotate",
    response_model=WebhookWithSecret,
    summary="Rotate the signing secret",
    description="The previous secret stops working immediately.",
)
async def rotate_webhook_secret(
    endpoint_id: str, principal: ManageWebhooks, session: DbSession
) -> WebhookWithSecret:
    service = WebhookService(session, principal.require_organization)
    endpoint = await service.rotate_secret(endpoint_id)
    return WebhookWithSecret(**_serialize(endpoint).model_dump(), secret=endpoint.secret)


@router.post(
    "/webhooks/{endpoint_id}/test",
    response_model=DeliveryResponse,
    summary="Send a test event",
    description="Delivers a real signed payload so an integrator can verify their receiver.",
)
async def test_webhook(
    endpoint_id: str, principal: ManageWebhooks, session: DbSession
) -> DeliveryResponse:
    service = WebhookService(session, principal.require_organization)
    endpoint = await service.endpoints.get_or_404(endpoint_id)

    delivery = WebhookDelivery(
        organization_id=endpoint.organization_id,
        endpoint_id=endpoint.id,
        event_type="verification.completed",
        event_id=f"evt_test_{endpoint.id[-8:]}",
        payload={
            "id": f"evt_test_{endpoint.id[-8:]}",
            "type": "verification.completed",
            "test": True,
            "data": {"decision": "verified", "similarity": 0.8121},
        },
        status="pending",
    )
    session.add(delivery)
    await session.flush()

    # Sent inline rather than queued: the whole point is that the integrator
    # sees the result while they are looking at the screen.
    await service.deliver(delivery)
    return _delivery(delivery)


@router.get(
    "/webhooks/{endpoint_id}/deliveries",
    response_model=list[DeliveryResponse],
    summary="Delivery log",
    description="Every attempt, including failures and the response we received.",
)
async def list_deliveries(
    endpoint_id: str,
    principal: ManageWebhooks,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[DeliveryResponse]:
    from sqlalchemy import select

    service = WebhookService(session, principal.require_organization)
    await service.endpoints.get_or_404(endpoint_id)

    rows = await session.execute(
        select(WebhookDelivery)
        .where(
            WebhookDelivery.organization_id == principal.require_organization,
            WebhookDelivery.endpoint_id == endpoint_id,
        )
        .order_by(WebhookDelivery.id.desc())
        .limit(limit)
    )
    return [_delivery(row) for row in rows.scalars()]


def _serialize(endpoint: WebhookEndpoint) -> WebhookResponse:
    return WebhookResponse(
        id=endpoint.id,
        url=endpoint.url,
        description=endpoint.description,
        events=list(endpoint.events or []),
        is_active=endpoint.is_active,
        failure_count=endpoint.failure_count,
        disabled_at=endpoint.disabled_at,
        last_delivery_at=endpoint.last_delivery_at,
        created_at=endpoint.created_at,
        secret_hint=f"{endpoint.secret[:11]}…{endpoint.secret[-4:]}",
    )


def _delivery(row: WebhookDelivery) -> DeliveryResponse:
    return DeliveryResponse(
        id=row.id,
        endpoint_id=row.endpoint_id,
        event_type=row.event_type,
        event_id=row.event_id,
        status=row.status,
        attempt_count=row.attempt_count,
        response_status=row.response_status,
        error=row.error,
        next_retry_at=row.next_retry_at,
        delivered_at=row.delivered_at,
        created_at=row.created_at,
    )
