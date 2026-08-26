"""Access logging.

One structured line per request. Deliberately does not log request bodies:
this API receives face images, and an access log is the last place they belong.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger("api.access")

# Health probes run every few seconds; logging them buries real traffic.
_QUIET_PATHS = frozenset({"/health", "/ready", "/metrics"})


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            # The exception handler produces the response; this records that the
            # request happened at all, which an errored request would otherwise lack.
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
            )
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Response-Time"] = f"{duration_ms}ms"

        if request.url.path not in _QUIET_PATHS:
            # `route` is the templated path (/v1/subjects/{id}), which is what
            # you want to aggregate on; `path` has the actual ID in it.
            route = request.scope.get("route")
            logger.info(
                "request",
                method=request.method,
                path=request.url.path,
                route=getattr(route, "path", None),
                status=response.status_code,
                duration_ms=duration_ms,
                client_ip=request.client.host if request.client else None,
            )

        return response
