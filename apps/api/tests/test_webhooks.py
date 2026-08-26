"""Webhook signing, delivery, and retry.

The delivery tests run against a **real receiver** — a small ASGI app that
verifies the signature the way the published snippet tells an integrator to.
Asserting that we *called* `sign()` would prove nothing about whether a customer
can actually validate what we send.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.biometrics.models import WebhookDelivery, WebhookEndpoint
from app.modules.identity.models import Organization
from app.modules.webhooks.service import MAX_ATTEMPTS, WebhookService
from app.modules.webhooks.signing import (
    EVENT_ID_HEADER,
    SIGNATURE_HEADER,
    generate_secret,
    sign,
    verify,
)
from tests.factories import Account, register

# ── Signing ───────────────────────────────────────────────────────────────────


def test_a_signature_verifies_against_its_payload() -> None:
    secret = generate_secret()
    payload = '{"id":"evt_1","type":"verification.completed"}'

    assert verify(payload, sign(payload, secret), secret) is True


def test_a_tampered_payload_fails() -> None:
    secret = generate_secret()
    header = sign('{"amount":10}', secret)

    assert verify('{"amount":1000}', header, secret) is False


def test_the_wrong_secret_fails() -> None:
    payload = '{"id":"evt_1"}'
    assert verify(payload, sign(payload, generate_secret()), generate_secret()) is False


def test_a_captured_request_cannot_be_replayed_later() -> None:
    """The timestamp is inside the MAC, so an old signature stays bound to its
    moment. Without that, one captured request would be valid forever.
    """
    secret = generate_secret()
    payload = '{"id":"evt_1"}'
    issued = int(time.time()) - 600

    header = sign(payload, secret, timestamp=issued)

    assert verify(payload, header, secret) is False
    # Still cryptographically intact — it is the age that disqualifies it.
    assert verify(payload, header, secret, tolerance_seconds=1200) is True


def test_a_future_timestamp_is_rejected_too() -> None:
    secret = generate_secret()
    payload = "{}"
    header = sign(payload, secret, timestamp=int(time.time()) + 600)
    assert verify(payload, header, secret) is False


@pytest.mark.parametrize(
    "header",
    ["", "garbage", "t=abc,v1=deadbeef", "v1=deadbeef", "t=123", "t=123;v1=x"],
)
def test_a_malformed_header_is_rejected_without_raising(header: str) -> None:
    """A receiver that distinguishes "malformed" from "wrong key" hands an
    attacker an oracle, so every failure mode returns the same False.
    """
    assert verify("{}", header, generate_secret()) is False


# ── A real receiver ───────────────────────────────────────────────────────────


class Receiver:
    """A customer endpoint. Records what arrived and whether it validated."""

    def __init__(self, secret: str | None = None, *, status_code: int = 200) -> None:
        self.secret = secret
        self.status_code = status_code
        self.received: list[dict[str, object]] = []

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break

        headers = {k.decode(): v.decode() for k, v in scope["headers"]}
        raw = body.decode()
        signature = headers.get(SIGNATURE_HEADER.lower(), "")

        self.received.append(
            {
                "body": json.loads(raw),
                "event_id": headers.get(EVENT_ID_HEADER.lower()),
                # Verified exactly as the docs tell an integrator to.
                "signature_valid": (verify(raw, signature, self.secret) if self.secret else None),
            }
        )

        await send({"type": "http.response.start", "status": self.status_code, "headers": []})
        await send({"type": "http.response.body", "body": b'{"ok":true}'})


@pytest.fixture
async def owner(client: AsyncClient) -> Account:
    account = await register(client, email="owner@acme.example.com", organization_name="Acme")
    return account


@pytest.fixture
async def paid_owner(client: AsyncClient, session: AsyncSession, owner: Account) -> Account:
    """Webhooks need a paid plan; Free does not include them."""
    organization = await session.get(Organization, owner.organization_id)
    assert organization is not None
    organization.plan = "growth"
    await session.commit()
    return owner


async def make_endpoint(
    client: AsyncClient,
    account: Account,
    *,
    url: str = "https://hooks.example.com/fvas",
    events: list[str] | None = None,
):
    return await client.post(
        "/v1/console/webhooks",
        json={"url": url, "events": events or ["verification.completed"]},
        headers=account.auth,
    )


# ── Endpoint management ───────────────────────────────────────────────────────


async def test_webhooks_require_a_paid_plan(client: AsyncClient, owner: Account) -> None:
    response = await make_endpoint(client, owner)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "plan_upgrade_required"


async def test_the_secret_is_returned_once_and_then_masked(
    client: AsyncClient, paid_owner: Account
) -> None:
    """A secret readable from a list endpoint lives in every browser cache and
    log that ever touched the console.
    """
    created = (await make_endpoint(client, paid_owner)).json()
    assert created["secret"].startswith("whsec_")

    listed = (await client.get("/v1/console/webhooks", headers=paid_owner.auth)).json()

    assert "secret" not in listed[0]
    assert listed[0]["secret_hint"].startswith("whsec_")
    assert "…" in listed[0]["secret_hint"]


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.com/fvas",
        "https://localhost/fvas",
        "https://127.0.0.1/fvas",
        "https://169.254.169.254/latest/meta-data/",
        "https://vault.internal/fvas",
    ],
)
async def test_unsafe_urls_are_refused(client: AsyncClient, paid_owner: Account, url: str) -> None:
    """Plain http would send signed customer data in clear text; loopback and
    link-local hosts would turn our delivery worker into an SSRF proxy.
    """
    response = await make_endpoint(client, paid_owner, url=url)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_webhook_url"


async def test_unknown_events_are_refused_with_the_supported_list(
    client: AsyncClient, paid_owner: Account
) -> None:
    response = await make_endpoint(client, paid_owner, events=["verification.exploded"])

    assert response.status_code == 400
    details = response.json()["error"]["details"]
    assert details["unknown"] == ["verification.exploded"]
    assert "verification.completed" in details["supported"]


async def test_rotating_the_secret_invalidates_the_old_one(
    client: AsyncClient, paid_owner: Account
) -> None:
    created = (await make_endpoint(client, paid_owner)).json()
    payload = '{"id":"evt_1"}'
    old_header = sign(payload, created["secret"])

    rotated = (
        await client.post(f"/v1/console/webhooks/{created['id']}/rotate", headers=paid_owner.auth)
    ).json()

    assert rotated["secret"] != created["secret"]
    assert verify(payload, old_header, rotated["secret"]) is False


# ── Delivery ──────────────────────────────────────────────────────────────────


async def test_a_delivery_is_signed_so_a_real_receiver_can_verify_it(
    session: AsyncSession, paid_owner: Account, client: AsyncClient
) -> None:
    created = (await make_endpoint(client, paid_owner)).json()
    receiver = Receiver(secret=created["secret"])

    service = WebhookService(session, paid_owner.organization_id)
    deliveries = await service.emit(
        "verification.completed", {"verification_id": "vs_1", "decision": "verified"}
    )
    await session.commit()
    assert len(deliveries) == 1

    async with httpx.AsyncClient(transport=ASGITransport(app=receiver)) as http:
        delivery = await service.deliver(deliveries[0], client=http)

    assert delivery.status == "delivered"
    assert delivery.response_status == 200
    assert delivery.delivered_at is not None

    assert len(receiver.received) == 1
    arrived = receiver.received[0]
    assert arrived["signature_valid"] is True, "the receiver could not verify our signature"
    assert arrived["event_id"] == delivery.event_id
    assert arrived["body"]["type"] == "verification.completed"  # type: ignore[index]
    assert arrived["body"]["data"]["verification_id"] == "vs_1"  # type: ignore[index]


async def test_only_subscribed_endpoints_receive_an_event(
    session: AsyncSession, paid_owner: Account, client: AsyncClient
) -> None:
    await make_endpoint(client, paid_owner, events=["verification.completed"])
    await make_endpoint(
        client, paid_owner, url="https://other.example.com/h", events=["subject.deleted"]
    )

    service = WebhookService(session, paid_owner.organization_id)
    deliveries = await service.emit("verification.completed", {"verification_id": "vs_1"})

    assert len(deliveries) == 1


async def test_a_failing_endpoint_is_retried_with_growing_backoff(
    session: AsyncSession, paid_owner: Account, client: AsyncClient
) -> None:
    created = (await make_endpoint(client, paid_owner)).json()
    receiver = Receiver(secret=created["secret"], status_code=500)

    service = WebhookService(session, paid_owner.organization_id)
    deliveries = await service.emit("verification.completed", {"verification_id": "vs_1"})
    await session.commit()
    delivery = deliveries[0]

    gaps: list[float] = []
    async with httpx.AsyncClient(transport=ASGITransport(app=receiver)) as http:
        from datetime import UTC, datetime

        for _ in range(3):
            await service.deliver(delivery, client=http)
            assert delivery.status == "pending"
            assert delivery.next_retry_at is not None
            gaps.append((delivery.next_retry_at - datetime.now(tz=UTC)).total_seconds())

    assert delivery.attempt_count == 3
    assert delivery.response_status == 500
    # 60s, 120s, 240s — each wait longer than the last.
    assert gaps[0] < gaps[1] < gaps[2]


async def test_delivery_gives_up_after_the_attempt_limit(
    session: AsyncSession, paid_owner: Account, client: AsyncClient
) -> None:
    created = (await make_endpoint(client, paid_owner)).json()
    receiver = Receiver(secret=created["secret"], status_code=503)

    service = WebhookService(session, paid_owner.organization_id)
    delivery = (await service.emit("verification.completed", {"v": 1}))[0]
    await session.commit()

    async with httpx.AsyncClient(transport=ASGITransport(app=receiver)) as http:
        for _ in range(MAX_ATTEMPTS):
            await service.deliver(delivery, client=http)

    assert delivery.attempt_count == MAX_ATTEMPTS
    assert delivery.status == "failed"
    assert delivery.next_retry_at is None


async def test_a_success_clears_the_consecutive_failure_count(
    session: AsyncSession, paid_owner: Account, client: AsyncClient
) -> None:
    """The count is consecutive, so an endpoint that mostly works is never
    disabled by an accumulation of unrelated blips.
    """
    created = (await make_endpoint(client, paid_owner)).json()
    service = WebhookService(session, paid_owner.organization_id)
    delivery = (await service.emit("verification.completed", {"v": 1}))[0]
    await session.commit()

    failing = Receiver(secret=created["secret"], status_code=500)
    async with httpx.AsyncClient(transport=ASGITransport(app=failing)) as http:
        await service.deliver(delivery, client=http)

    endpoint = await session.get(WebhookEndpoint, created["id"])
    assert endpoint is not None
    assert endpoint.failure_count == 1

    working = Receiver(secret=created["secret"])
    async with httpx.AsyncClient(transport=ASGITransport(app=working)) as http:
        await service.deliver(delivery, client=http)

    await session.refresh(endpoint)
    assert endpoint.failure_count == 0
    assert endpoint.last_delivery_at is not None


async def test_a_test_send_reaches_a_real_receiver(
    client: AsyncClient, paid_owner: Account, session: AsyncSession
) -> None:
    """The endpoint an integrator clicks while watching their own logs."""
    created = (await make_endpoint(client, paid_owner)).json()

    response = await client.post(
        f"/v1/console/webhooks/{created['id']}/test", headers=paid_owner.auth
    )

    assert response.status_code == 200
    body = response.json()
    assert body["event_type"] == "verification.completed"
    assert body["attempt_count"] == 1
    # hooks.example.com does not exist, so this records a real failure rather
    # than pretending. That is the honest outcome and the log shows it.
    assert body["status"] in {"pending", "failed"}
    assert body["error"]


async def test_the_delivery_log_records_every_attempt(
    client: AsyncClient, paid_owner: Account
) -> None:
    created = (await make_endpoint(client, paid_owner)).json()
    await client.post(f"/v1/console/webhooks/{created['id']}/test", headers=paid_owner.auth)
    await client.post(f"/v1/console/webhooks/{created['id']}/test", headers=paid_owner.auth)

    log = (
        await client.get(
            f"/v1/console/webhooks/{created['id']}/deliveries", headers=paid_owner.auth
        )
    ).json()

    assert len(log) == 2
    assert all(entry["attempt_count"] >= 1 for entry in log)


# ── Integration with verification ─────────────────────────────────────────────


async def test_a_verification_queues_an_event(
    client: AsyncClient, paid_owner: Account, session: AsyncSession
) -> None:
    from tests.factories import create_subject, enroll, frame, frames

    await make_endpoint(
        client, paid_owner, events=["verification.completed", "verification.failed"]
    )

    subject = await create_subject(client, paid_owner, external_id="user_1")
    await enroll(client, paid_owner, subject["id"], images=frames(1, 3))
    await client.post(
        "/v1/console/verifications",
        json={"subject_id": subject["id"], "image": frame(1, seed=77)},
        headers=paid_owner.auth,
    )

    rows = list((await session.execute(select(WebhookDelivery))).scalars())

    assert len(rows) == 1
    assert rows[0].event_type == "verification.completed"
    assert rows[0].payload["data"]["decision"] == "verified"


async def test_a_broken_webhook_never_fails_the_verification(
    client: AsyncClient, paid_owner: Account, session: AsyncSession
) -> None:
    """A webhook subscription is a side channel. A customer's misconfigured
    endpoint must not be able to break their own authentication flow.
    """
    from tests.factories import create_subject, enroll, frame, frames

    endpoint_id = (await make_endpoint(client, paid_owner)).json()["id"]
    endpoint = await session.get(WebhookEndpoint, endpoint_id)
    assert endpoint is not None
    # Corrupt the row so emitting raises rather than merely failing to deliver.
    endpoint.events = None  # type: ignore[assignment]
    await session.commit()

    subject = await create_subject(client, paid_owner, external_id="user_1")
    await enroll(client, paid_owner, subject["id"], images=frames(1, 3))

    response = await client.post(
        "/v1/console/verifications",
        json={"subject_id": subject["id"], "image": frame(1, seed=77)},
        headers=paid_owner.auth,
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "verified"
