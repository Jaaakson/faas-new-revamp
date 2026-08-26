"""Domain exceptions and the single error envelope.

Services raise domain exceptions; they know nothing about HTTP. One set of
handlers maps them to responses, which is what lets a service run from a CLI,
a worker, or a test without an HTTP stack.

Every non-2xx response has the same shape (docs/07-api-design.md §2):

    {"error": {"code": ..., "message": ..., "details": ..., "request_id": ...}}
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import get_request_id

logger = structlog.get_logger(__name__)


class FvasError(Exception):
    """Base for every expected, domain-level failure."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details
        if code:
            self.code = code
        super().__init__(self.message)


class BadRequestError(FvasError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "invalid_request"
    message = "The request could not be understood."


class UnauthenticatedError(FvasError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthenticated"
    message = "Authentication credentials were missing or invalid."


class ForbiddenError(FvasError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"
    message = "You do not have permission to perform this action."


class NotFoundError(FvasError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "The requested resource does not exist."


class ConflictError(FvasError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "The request conflicts with the current state of the resource."


class PayloadTooLargeError(FvasError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "payload_too_large"
    message = "The request payload exceeds the maximum allowed size."


class UnprocessableError(FvasError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "unprocessable_entity"
    message = "The request was well-formed but semantically invalid."


class RateLimitedError(FvasError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Too many requests. Slow down."

    def __init__(self, retry_after: int = 60, **kwargs: Any) -> None:
        self.retry_after = retry_after
        super().__init__(**kwargs)


class ServiceUnavailableError(FvasError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"
    message = "The service is temporarily unavailable."


def error_body(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the error envelope. The only place its shape is defined."""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": get_request_id(),
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the handlers that guarantee a uniform error shape."""

    @app.exception_handler(FvasError)
    async def _handle_domain_error(_: Request, exc: FvasError) -> JSONResponse:
        headers: dict[str, str] = {}
        if isinstance(exc, RateLimitedError):
            headers["Retry-After"] = str(exc.retry_after)

        # 5xx is our fault and deserves a stack trace; 4xx is the caller's and does not.
        if exc.status_code >= 500:
            logger.error("domain_error", code=exc.code, message=exc.message, exc_info=exc)
        else:
            logger.info("domain_error", code=exc.code, message=exc.message)

        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Flatten Pydantic's error list into something a client can act on
        # without needing to understand Pydantic's internal structure.
        fields = [
            {
                "field": ".".join(str(part) for part in error["loc"][1:]) or "body",
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=error_body(
                "invalid_request",
                "The request failed validation.",
                {"fields": fields},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Covers framework-raised 404/405 so even routing errors keep the envelope.
        codes = {
            status.HTTP_401_UNAUTHORIZED: "unauthenticated",
            status.HTTP_403_FORBIDDEN: "forbidden",
            status.HTTP_404_NOT_FOUND: "not_found",
            status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
        }
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(
                codes.get(exc.status_code, "http_error"),
                str(exc.detail),
            ),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Never leak internals. The request_id is the bridge between what the
        # caller sees and the stack trace in our logs.
        logger.exception("unhandled_exception", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body(
                "internal_error",
                "An unexpected error occurred. Quote the request_id when reporting this.",
            ),
        )
