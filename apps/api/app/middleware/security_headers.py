"""Security headers.

Applied to every response, including errors. See docs/09-security.md §5 for the
reasoning behind each one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings

BASE_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # The API itself never needs a camera; the browser capture happens in the
    # web app. Being explicit about what a biometric service does NOT access
    # is a meaningful trust signal.
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    # The API returns JSON only, so a restrictive CSP costs nothing and blocks
    # rendering of any response that somehow becomes HTML.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
}

HSTS = "max-age=63072000; includeSubDomains; preload"

# Swagger UI loads its own assets and inline styles, so the API-wide CSP has to
# relax for those two paths only.
_DOCS_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect"})
_DOCS_CSP = (
    "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)

        for header, value in BASE_HEADERS.items():
            response.headers.setdefault(header, value)

        if request.url.path in _DOCS_PATHS:
            response.headers["Content-Security-Policy"] = _DOCS_CSP

        # HSTS over plaintext is meaningless and can confuse local development.
        if settings.is_production:
            response.headers.setdefault("Strict-Transport-Security", HSTS)

        return response
