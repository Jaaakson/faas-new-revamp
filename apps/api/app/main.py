"""Application factory.

Composition happens here and only here: middleware order, router mounting,
lifespan. Keeping it in one readable file means the request path can be
understood without tracing imports across the package.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import dispose_engine
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.permissions import assert_matrix_is_complete
from app.core.redis import close_redis
from app.middleware import (
    AccessLogMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
)
from app.modules.analytics.router import router as analytics_router
from app.modules.auth.router import router as auth_router
from app.modules.biometrics.engine.registry import load_engine
from app.modules.biometrics.router import router as biometrics_router
from app.modules.biometrics.verification_router import router as verification_router
from app.modules.identity.api_key_router import router as api_key_router
from app.modules.identity.router import router as identity_router
from app.modules.platform.router import router as platform_router
from app.modules.public_api.router import router as public_router
from app.modules.webhooks.router import router as webhooks_router

logger = structlog.get_logger(__name__)

DESCRIPTION = """
Face authentication as an API. Enroll a subject once, verify them in under a
second, and get an audit trail for every decision.

**Two authentication surfaces:**

* `/v1/*` — the public API, authenticated with an API key (`Authorization: Bearer fvas_live_…`)
* `/v1/console/*` — the dashboard API, authenticated with a JWT

A failed *verification* is a `200` with `"decision": "rejected"` — that is a
successful answer to the question asked. Only a failed *request* is an error.
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown.

    Expensive, long-lived resources are acquired here rather than lazily. This
    is where the ONNX face models load: a lazy first-request load would give the
    first user of every deploy a multi-second verification, and would do the
    loading while holding the event loop.
    """
    configure_logging()
    settings.assert_production_safe()

    # Cheap, and it catches two mistakes that are otherwise invisible: a
    # permission no role can exercise, and a role that outranks Owner.
    assert_matrix_is_complete()

    # ~1 s of file I/O and graph optimisation for the real engine. Off the loop
    # thread so a slow disk cannot stall the ASGI startup handshake; startup
    # still waits for it, which is the point — the process must not report ready
    # while it would fail every verification.
    await asyncio.to_thread(load_engine)

    logger.info(
        "startup",
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
    )
    try:
        yield
    finally:
        logger.info("shutdown")
        await close_redis()
        await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description=DESCRIPTION,
        version=settings.APP_VERSION,
        lifespan=lifespan,
        docs_url=settings.docs_url,
        redoc_url=settings.redoc_url,
        openapi_url=None if settings.is_production else "/openapi.json",
        contact={"name": "Fvas", "url": "https://fvas.io"},
        license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
        openapi_tags=[
            {"name": "Platform", "description": "Liveness and readiness probes."},
            {
                "name": "Public API",
                "description": (
                    "What your backend calls. Authenticated with an API key: "
                    "`Authorization: Bearer fvas_live_…`. Confined to biometric "
                    "operations — it cannot reach settings, members, or billing."
                ),
            },
            {
                "name": "Verification",
                "description": (
                    "The core loop. A rejected verification is a 200 - only a failed "
                    "request is an error, and `inconclusive` is never collapsed into "
                    "`rejected`."
                ),
            },
            {
                "name": "Biometrics",
                "description": (
                    "Subjects and enrollment. A subject is one of your end users; "
                    "enrolling creates the versioned face profile that verification "
                    "later matches against."
                ),
            },
        ],
    )

    # Starlette runs middleware in reverse registration order, so this list
    # executes bottom-up: security headers are added last (wrapping every
    # response, including errors), request IDs are assigned first.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
        # Rate-limit headers are documented as present on every response
        # (docs/07-api-design.md §2). Without exposing them here a browser
        # client can see the 429 but not how long to wait, which makes the
        # documented contract true only for server-side callers.
        expose_headers=[
            "X-Request-ID",
            "X-Response-Time",
            "Retry-After",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "Idempotent-Replay",
        ],
        max_age=600,
    )
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIDMiddleware)

    register_exception_handlers(app)

    app.include_router(platform_router)

    # The console surface. Separate from the public `/v1` API so a stolen API
    # key can never reach organization settings, members, or billing.
    console = APIRouter(prefix=f"{settings.API_V1_PREFIX}/console")
    console.include_router(auth_router)
    console.include_router(identity_router)
    console.include_router(api_key_router)
    console.include_router(biometrics_router)
    console.include_router(verification_router)
    console.include_router(webhooks_router)
    console.include_router(analytics_router)
    app.include_router(console)

    # The public surface. Mounted separately from the console so a stolen
    # API key can never reach settings, members, billing, audit logs, or
    # other keys — the separation is structural, not a scope check that
    # someone might forget to add to a new endpoint.
    app.include_router(public_router, prefix=settings.API_V1_PREFIX)

    return app


app = create_app()
