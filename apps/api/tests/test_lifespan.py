"""Application startup and shutdown.

These exist because the rest of the suite drives the app through
`httpx.ASGITransport`, which does **not** run the lifespan. That gap let a
startup crash (a logging processor incompatible with the configured logger
factory) pass a fully green test run and only surface when a real server
booted.

`TestClient` as a context manager runs startup on enter and shutdown on exit,
which is the cheapest possible guard against "the process does not start".
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.main import create_app
from app.modules.biometrics.engine.registry import build_engine, get_engine, reset_engine


def test_application_starts_and_serves() -> None:
    """The whole lifespan runs: logging configured, probes reachable."""
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200


def test_application_shuts_down_cleanly() -> None:
    """Exiting the context runs shutdown; a raised exception fails the test."""
    with TestClient(create_app()) as client:
        client.get("/health")


def test_logging_configuration_is_usable_after_startup() -> None:
    """Emit through every level and processor the real app uses.

    Configuring structlog successfully is not the same as being able to log —
    the original bug was in a processor, which only runs on an actual call.
    """
    import structlog

    with TestClient(create_app()):
        logger = structlog.get_logger("test.logger")
        logger.info("event_with_context", org_id="org_123", password="hunter2")
        logger.warning("warning_event")
        logger.error("error_event", detail={"nested": {"token": "abc"}})


def test_face_engine_is_loaded_during_startup() -> None:
    """The engine must be ready before the first request, not on first use.

    `get_engine()` raises unless the lifespan populated the singleton, so this
    also proves the accessor is usable from a request handler.
    """
    reset_engine()
    with TestClient(create_app()) as client:
        client.get("/health")
        assert get_engine().model.name == "fake"


def test_face_engine_load_is_idempotent() -> None:
    """Two app instances in one process share the singleton.

    Re-loading would double the memory footprint of the ONNX weights for no
    benefit, and the suite creates apps freely.
    """
    reset_engine()
    with TestClient(create_app()):
        first = get_engine()
    with TestClient(create_app()):
        assert get_engine() is first


def test_startup_refuses_a_fake_engine_in_production() -> None:
    """A fake engine in production accepts every face. Refuse to start.

    This is the one configuration mistake in the biometric path that is silent:
    the service would look healthy and verify everyone.
    """
    monkey = settings.FACE_ENGINE, settings.ENVIRONMENT
    try:
        object.__setattr__(settings, "FACE_ENGINE", "fake")
        object.__setattr__(settings, "ENVIRONMENT", "production")
        with pytest.raises(RuntimeError, match="would accept any face"):
            build_engine()
    finally:
        object.__setattr__(settings, "FACE_ENGINE", monkey[0])
        object.__setattr__(settings, "ENVIRONMENT", monkey[1])


def test_startup_refuses_an_unsafe_production_config() -> None:
    """A misconfigured production deploy must crash in the first second.

    Serving traffic with DEBUG on and plaintext origins is worse than not
    starting at all.
    """
    unsafe = Settings(
        ENVIRONMENT="production",
        DEBUG=True,
        COOKIE_SECURE=False,
        CORS_ORIGINS="http://app.fvas.io",
        JWT_SECRET_KEY="tooshort",
    )
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        unsafe.assert_production_safe()


async def test_production_emits_hsts_and_development_does_not() -> None:
    """HSTS over plaintext is meaningless, so it is gated on production.

    Verified here rather than against a container, because a production
    container refuses to boot at all without the real face engine — which is
    itself the more important guarantee, asserted above.
    """
    from httpx import ASGITransport, AsyncClient

    original = settings.ENVIRONMENT
    try:
        object.__setattr__(settings, "ENVIRONMENT", "production")
        async with AsyncClient(
            transport=ASGITransport(app=create_app()), base_url="http://test"
        ) as client:
            production = await client.get("/health")

        object.__setattr__(settings, "ENVIRONMENT", "development")
        async with AsyncClient(
            transport=ASGITransport(app=create_app()), base_url="http://test"
        ) as client:
            development = await client.get("/health")
    finally:
        object.__setattr__(settings, "ENVIRONMENT", original)

    assert production.headers["strict-transport-security"].startswith("max-age=")
    assert "includeSubDomains" in production.headers["strict-transport-security"]
    assert "strict-transport-security" not in development.headers


async def test_every_response_carries_the_baseline_security_headers() -> None:
    """Measured against a real response, not against the middleware's source."""
    with TestClient(create_app()) as client:
        headers = client.get("/health").headers

    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert "strict-origin" in headers["referrer-policy"]
    # The capture UI asks for the camera; nothing else should be able to.
    assert "microphone=()" in headers["permissions-policy"]
    assert "geolocation=()" in headers["permissions-policy"]
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
