"""Health, readiness, and the response contract every endpoint inherits."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.middleware.security_headers import BASE_HEADERS


def _patch_probes(monkeypatch: pytest.MonkeyPatch, *, database: bool, redis: bool) -> None:
    """Control dependency health explicitly.

    Without this the result depends on what happens to be running: SQLite
    in-memory always connects, so the database probe would pass locally and the
    test would assert something different in CI.
    """

    async def _database() -> bool:
        return database

    async def _redis() -> bool:
        return redis

    monkeypatch.setattr("app.modules.platform.router.check_database", _database)
    monkeypatch.setattr("app.modules.platform.router.check_redis", _redis)


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "Fvas"
    assert body["environment"] == "test"


async def test_health_does_not_depend_on_the_database(client: AsyncClient) -> None:
    """Liveness must stay green while dependencies are down.

    Otherwise a database blip makes the orchestrator restart every healthy
    container in a loop, turning a partial outage into a total one.
    """
    response = await client.get("/health")
    assert response.status_code == 200


async def test_ready_returns_200_when_everything_is_reachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_probes(monkeypatch, database=True, redis=True)

    response = await client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert {dep["name"] for dep in body["dependencies"]} == {"database", "redis"}
    assert all(dep["healthy"] for dep in body["dependencies"])


@pytest.mark.parametrize(
    ("database_ok", "redis_ok"),
    [(False, True), (True, False), (False, False)],
)
async def test_ready_returns_503_when_any_dependency_is_down(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    database_ok: bool,
    redis_ok: bool,
) -> None:
    """503 is what makes the load balancer stop routing here.

    Returning 200 with a "degraded" body would keep sending users to a process
    that cannot serve them.
    """
    _patch_probes(monkeypatch, database=database_ok, redis=redis_ok)

    response = await client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"

    reported = {dep["name"]: dep["healthy"] for dep in body["dependencies"]}
    assert reported == {"database": database_ok, "redis": redis_ok}


async def test_request_id_is_generated_and_returned(client: AsyncClient) -> None:
    response = await client.get("/health")

    request_id = response.headers["X-Request-ID"]
    assert request_id.startswith("req_")


async def test_inbound_request_id_is_propagated(client: AsyncClient) -> None:
    """A trace surviving the hop from the Next.js BFF is the whole point."""
    response = await client.get("/health", headers={"X-Request-ID": "req_from_bff_123"})

    assert response.headers["X-Request-ID"] == "req_from_bff_123"


async def test_malformed_inbound_request_id_is_replaced(client: AsyncClient) -> None:
    """An inbound header is untrusted input that we echo and log.

    Accepting it verbatim would allow log injection via newlines.
    """
    response = await client.get("/health", headers={"X-Request-ID": "bad value\nwith newline"})

    returned = response.headers["X-Request-ID"]
    assert returned.startswith("req_")
    assert "\n" not in returned


async def test_security_headers_present(client: AsyncClient) -> None:
    response = await client.get("/health")

    for header, expected in BASE_HEADERS.items():
        assert response.headers.get(header) == expected, f"missing header: {header}"


async def test_response_time_header(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers["X-Response-Time"].endswith("ms")
