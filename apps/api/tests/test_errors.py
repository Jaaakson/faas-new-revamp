"""The error envelope.

One shape for every non-2xx response, including framework-raised ones. A client
that can branch on `error.code` for a domain failure but has to sniff HTML for
a 404 does not have a contract.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import (
    ConflictError,
    FvasError,
    NotFoundError,
    RateLimitedError,
    register_exception_handlers,
)


@pytest.fixture
async def failing_client() -> AsyncClient:
    """An app whose routes exist only to raise."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/not-found")
    async def _not_found() -> None:
        raise NotFoundError("Subject 'sub_missing' was not found.")

    @app.get("/conflict")
    async def _conflict() -> None:
        raise ConflictError(details={"external_id": "user_84213"})

    @app.get("/rate-limited")
    async def _rate_limited() -> None:
        raise RateLimitedError(retry_after=30)

    @app.get("/boom")
    async def _boom() -> None:
        raise ValueError("an internal detail that must never reach the client")

    # raise_app_exceptions=False lets the registered handler produce the 500
    # response instead of the exception propagating into the test.
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


async def test_domain_error_uses_the_envelope(failing_client: AsyncClient) -> None:
    response = await failing_client.get("/not-found")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert "sub_missing" in error["message"]
    assert "request_id" in error


async def test_details_are_structured(failing_client: AsyncClient) -> None:
    response = await failing_client.get("/conflict")

    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"external_id": "user_84213"}


async def test_rate_limit_sets_retry_after(failing_client: AsyncClient) -> None:
    response = await failing_client.get("/rate-limited")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"


async def test_unexpected_exception_does_not_leak_internals(
    failing_client: AsyncClient,
) -> None:
    response = await failing_client.get("/boom")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert "an internal detail" not in error["message"]
    assert "ValueError" not in error["message"]


async def test_unknown_route_keeps_the_envelope(failing_client: AsyncClient) -> None:
    """Framework-raised 404s must not fall back to Starlette's plain shape."""
    response = await failing_client.get("/no-such-route")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    ("exception", "expected_status", "expected_code"),
    [
        (NotFoundError, 404, "not_found"),
        (ConflictError, 409, "conflict"),
    ],
)
def test_exception_status_and_code_mapping(
    exception: type[FvasError], expected_status: int, expected_code: str
) -> None:
    instance = exception()
    assert instance.status_code == expected_status
    assert instance.code == expected_code
