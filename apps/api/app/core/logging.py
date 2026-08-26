"""Structured logging.

JSON in staging and production so logs are queryable; a human-readable
renderer in development. Every event carries the request ID automatically,
which is what makes an incident reconstructable from a single support ticket.

Hard rule (docs/05-architecture.md §10): never log image bytes, embeddings,
tokens, API key secrets, or passwords. `SENSITIVE_KEYS` is enforced by a
processor here and asserted by a test.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.core.config import settings
from app.core.context import get_request_id

SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "jwt",
        "authorization",
        "api_key",
        "key_hash",
        "secret",
        "embedding",
        "embeddings",
        "image",
        "images",
        "image_data",
        "consent_reference",
    }
)

REDACTED = "[redacted]"


def _redact_sensitive(_: Any, __: str, event_dict: EventDict) -> EventDict:
    """Replace the value of any sensitive key, at any nesting depth."""

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: REDACTED if k.lower() in SENSITIVE_KEYS else scrub(v) for k, v in value.items()
            }
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    for key in list(event_dict.keys()):
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = REDACTED
        else:
            event_dict[key] = scrub(event_dict[key])
    return event_dict


def _add_request_id(_: Any, __: str, event_dict: EventDict) -> EventDict:
    request_id = get_request_id()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging() -> None:
    """Configure structlog and route the stdlib logging tree through it."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _add_request_id,
        _redact_sensitive,
    ]

    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if settings.LOG_FORMAT == "json"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[
            *shared,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.LOG_LEVEL)
        ),
        # The stdlib factory, not PrintLoggerFactory: `add_logger_name` reads
        # `logger.name`, which only a stdlib logger has. It also puts structlog
        # and library logging (uvicorn, SQLAlchemy) through one handler, so
        # everything reaching stdout has the same shape.
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # `%(message)s` only: the record's message is already a fully rendered JSON
    # line, so any further formatting would corrupt it.
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=settings.LOG_LEVEL)
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine"):
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = False
