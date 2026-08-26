"""Redis client.

Used for rate limiting, idempotency caching, and the refresh-token denylist.
Redis being unavailable degrades those features but must never take down the
process at import time, so the client is created lazily.
"""

from __future__ import annotations

import structlog
from redis.asyncio import Redis, from_url

from app.core.config import settings

logger = structlog.get_logger(__name__)

_client: Redis | None = None


def get_redis() -> Redis:
    """Return the shared client, creating it on first use."""
    global _client
    if _client is None:
        _client = from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
    return _client


async def check_redis() -> bool:
    """Readiness probe. Returns False rather than raising."""
    try:
        return bool(await get_redis().ping())
    except Exception as exc:
        logger.warning("redis_unavailable", error=str(exc))
        return False


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
