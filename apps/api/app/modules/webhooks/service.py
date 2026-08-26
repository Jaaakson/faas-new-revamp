"""Webhook endpoints and delivery.

Delivery is **at-least-once and persisted**. Every attempt is a row, and the
retry schedule lives in `next_retry_at` rather than in memory, for two reasons:
a process restart must not lose a pending delivery, and "did you send it?" is
the first question in every webhook support thread — an answer of "probably" is
worthless.

Receivers must dedupe on `Fvas-Event-Id`. That is documented prominently rather
than as a footnote, because at-least-once means duplicates are a normal
occurrence and not an incident.

Backoff is exponential with a cap: roughly 1 min, 2, 4, 8, 16, 32, 64, 128 —
eight attempts spanning about four hours. After
`MAX_CONSECUTIVE_FAILURES` the endpoint is disabled: at that point it is not
"temporarily down", it is gone, and continuing to retry costs us a worker and
them nothing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog
from sqlalchemy import select

from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.core.plans import get_plan
from app.modules.biometrics.models import (
    MAX_CONSECUTIVE_FAILURES,
    WEBHOOK_EVENTS,
    WebhookDelivery,
    WebhookEndpoint,
)
from app.modules.identity.models import Organization
from app.modules.webhooks.signing import (
    EVENT_ID_HEADER,
    EVENT_TYPE_HEADER,
    SIGNATURE_HEADER,
    generate_secret,
    sign,
)
from app.shared.base_repository import TenantScopedRepository
from app.shared.utils import ids

logger = structlog.get_logger(__name__)

MAX_ATTEMPTS = 8
# Seconds. Doubling, capped so the last gaps stay useful rather than arriving
# after the customer has already noticed and fixed the endpoint themselves.
BACKOFF_BASE_SECONDS = 60
BACKOFF_CAP_SECONDS = 2 * 60 * 60

DELIVERY_TIMEOUT_SECONDS = 10
# A receiver returning a large error page must not be able to fill our database.
RESPONSE_SNIPPET_LIMIT = 900


class WebhookEndpointRepository(TenantScopedRepository[WebhookEndpoint]):
    model = WebhookEndpoint


class WebhookDeliveryRepository(TenantScopedRepository[WebhookDelivery]):
    model = WebhookDelivery


class WebhookService:
    def __init__(self, session: Any, organization_id: str) -> None:
        self.session = session
        self.organization_id = organization_id
        self.endpoints = WebhookEndpointRepository(session, organization_id)
        self.deliveries = WebhookDeliveryRepository(session, organization_id)

    # ── Endpoint management ───────────────────────────────────────────────────

    async def create_endpoint(
        self, *, url: str, events: list[str], description: str | None
    ) -> WebhookEndpoint:
        await self._assert_plan_allows_webhooks()
        _assert_valid_url(url)
        _assert_known_events(events)

        endpoint = WebhookEndpoint(
            organization_id=self.organization_id,
            url=url,
            description=description,
            events=events,
            # Per-endpoint, not per-organization: rotating one integration's
            # secret must not invalidate signatures for all the others.
            secret=generate_secret(),
        )
        self.session.add(endpoint)
        await self.session.commit()
        return endpoint

    async def list_endpoints(self) -> list[WebhookEndpoint]:
        result = await self.session.execute(
            self.endpoints._scoped().order_by(WebhookEndpoint.id.desc())
        )
        return list(result.scalars())

    async def update_endpoint(self, endpoint_id: str, **values: Any) -> WebhookEndpoint:
        endpoint = await self.endpoints.get_or_404(endpoint_id)
        if values.get("url"):
            _assert_valid_url(values["url"])
        if "events" in values and values["events"] is not None:
            _assert_known_events(values["events"])

        for field, value in values.items():
            if value is not None:
                setattr(endpoint, field, value)

        if values.get("is_active"):
            # Re-enabling clears the strike count, otherwise an endpoint that was
            # auto-disabled would be one failure away from being disabled again.
            endpoint.failure_count = 0
            endpoint.disabled_at = None

        await self.session.commit()
        return endpoint

    async def delete_endpoint(self, endpoint_id: str) -> None:
        endpoint = await self.endpoints.get_or_404(endpoint_id)
        endpoint.deleted_at = datetime.now(tz=UTC)
        endpoint.is_active = False
        await self.session.commit()

    async def rotate_secret(self, endpoint_id: str) -> WebhookEndpoint:
        endpoint = await self.endpoints.get_or_404(endpoint_id)
        endpoint.secret = generate_secret()
        await self.session.commit()
        return endpoint

    # ── Emitting ──────────────────────────────────────────────────────────────

    async def emit(self, event_type: str, data: dict[str, Any]) -> list[WebhookDelivery]:
        """Queue one event for every endpoint subscribed to it.

        Rows only — nothing is sent here. Emitting happens inside the request
        that produced the event, and a slow customer endpoint must never be able
        to add ten seconds to a verification.
        """
        if event_type not in WEBHOOK_EVENTS:
            raise ValueError(f"unknown webhook event: {event_type}")

        result = await self.session.execute(
            self.endpoints._scoped().where(WebhookEndpoint.is_active.is_(True))
        )
        endpoints = [e for e in result.scalars() if event_type in (e.events or [])]
        if not endpoints:
            return []

        event_id = ids.new_id("evt")
        now = datetime.now(tz=UTC)
        queued: list[WebhookDelivery] = []

        for endpoint in endpoints:
            delivery = WebhookDelivery(
                organization_id=self.organization_id,
                endpoint_id=endpoint.id,
                event_type=event_type,
                # Shared across endpoints: it identifies the *event*, and a
                # receiver subscribed twice should recognise it as one thing.
                event_id=event_id,
                payload={
                    "id": event_id,
                    "type": event_type,
                    "created_at": now.isoformat(),
                    "data": data,
                },
                status="pending",
                next_retry_at=now,
            )
            self.session.add(delivery)
            queued.append(delivery)

        await self.session.flush()
        return queued

    # ── Delivering ────────────────────────────────────────────────────────────

    async def deliver(
        self, delivery: WebhookDelivery, *, client: httpx.AsyncClient | None = None
    ) -> WebhookDelivery:
        """Attempt one delivery and record the outcome."""
        endpoint = await self.session.get(WebhookEndpoint, delivery.endpoint_id)
        if endpoint is None:
            delivery.status = "failed"
            delivery.error = "endpoint no longer exists"
            await self.session.commit()
            return delivery

        body = json.dumps(delivery.payload, separators=(",", ":"), default=str)
        headers = {
            "Content-Type": "application/json",
            SIGNATURE_HEADER: sign(body, endpoint.secret),
            EVENT_ID_HEADER: delivery.event_id,
            EVENT_TYPE_HEADER: delivery.event_type,
            "User-Agent": "Fvas-Webhooks/1.0",
        }

        delivery.attempt_count += 1
        owns_client = client is None
        client = client or httpx.AsyncClient(timeout=DELIVERY_TIMEOUT_SECONDS)

        try:
            response = await client.post(endpoint.url, content=body, headers=headers)
            delivery.response_status = response.status_code
            delivery.response_body = response.text[:RESPONSE_SNIPPET_LIMIT]

            if 200 <= response.status_code < 300:
                delivery.status = "delivered"
                delivery.delivered_at = datetime.now(tz=UTC)
                delivery.next_retry_at = None
                # Consecutive, so an endpoint that mostly works is never
                # disabled by an accumulation of unrelated blips.
                endpoint.failure_count = 0
                endpoint.last_delivery_at = delivery.delivered_at
            else:
                self._schedule_retry(delivery, endpoint, f"HTTP {response.status_code}")
        except (httpx.HTTPError, OSError) as exc:
            self._schedule_retry(delivery, endpoint, f"{type(exc).__name__}: {exc}"[:490])
        finally:
            if owns_client:
                await client.aclose()

        await self.session.commit()
        return delivery

    def _schedule_retry(
        self, delivery: WebhookDelivery, endpoint: WebhookEndpoint, error: str
    ) -> None:
        delivery.error = error
        endpoint.failure_count += 1

        if delivery.attempt_count >= MAX_ATTEMPTS:
            delivery.status = "failed"
            delivery.next_retry_at = None
        else:
            backoff = min(
                BACKOFF_BASE_SECONDS * (2 ** (delivery.attempt_count - 1)),
                BACKOFF_CAP_SECONDS,
            )
            delivery.status = "pending"
            delivery.next_retry_at = datetime.now(tz=UTC) + timedelta(seconds=backoff)

        if endpoint.failure_count >= MAX_CONSECUTIVE_FAILURES and endpoint.is_active:
            endpoint.is_active = False
            endpoint.disabled_at = datetime.now(tz=UTC)
            logger.warning(
                "webhook_endpoint_disabled",
                endpoint_id=endpoint.id,
                failures=endpoint.failure_count,
            )

    async def due_deliveries(self, *, limit: int = 50) -> list[WebhookDelivery]:
        """Pending deliveries whose retry time has arrived."""
        now = datetime.now(tz=UTC)
        result = await self.session.execute(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.organization_id == self.organization_id,
                WebhookDelivery.status == "pending",
                WebhookDelivery.next_retry_at <= now,
            )
            .order_by(WebhookDelivery.next_retry_at)
            .limit(limit)
        )
        return list(result.scalars())

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _assert_plan_allows_webhooks(self) -> None:
        organization = await self.session.get(Organization, self.organization_id)
        plan = get_plan(organization.plan if organization else "free")
        if not plan.webhooks_enabled:
            raise ForbiddenError(
                f"Webhooks are not available on the {plan.name} plan.",
                code="plan_upgrade_required",
                details={"plan": plan.name, "required": "startup"},
            )


def _assert_valid_url(url: str) -> None:
    """Reject anything that is not an https URL to somewhere else.

    Plain http would send signed customer data in clear text. Blocking loopback
    and link-local hosts is SSRF defence: without it, a customer could point an
    endpoint at `http://169.254.169.254/` and have us fetch cloud credentials on
    their behalf.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise BadRequestError(
            "Webhook URLs must use https.",
            code="invalid_webhook_url",
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise BadRequestError("Webhook URL is missing a host.", code="invalid_webhook_url")

    blocked = ("localhost", "127.0.0.1", "::1", "0.0.0.0", "169.254.169.254")  # noqa: S104
    if host in blocked or host.endswith(".local") or host.endswith(".internal"):
        raise BadRequestError(
            "Webhook URLs must point at a public host.",
            code="invalid_webhook_url",
            details={"host": host},
        )


def _assert_known_events(events: list[str]) -> None:
    if not events:
        raise BadRequestError(
            "Subscribe to at least one event.",
            code="invalid_webhook_events",
        )
    unknown = sorted(set(events) - set(WEBHOOK_EVENTS))
    if unknown:
        raise BadRequestError(
            f"Unknown webhook events: {', '.join(unknown)}.",
            code="invalid_webhook_events",
            details={"unknown": unknown, "supported": list(WEBHOOK_EVENTS)},
        )


async def endpoint_or_404(service: WebhookService, endpoint_id: str) -> WebhookEndpoint:
    endpoint = await service.endpoints.get(endpoint_id)
    if endpoint is None:
        raise NotFoundError(f"Webhook endpoint '{endpoint_id}' was not found.")
    return endpoint
