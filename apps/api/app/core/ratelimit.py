"""Token-bucket rate limiting and idempotency, both backed by Redis.

They share a file because they share a failure question: **what happens when
Redis is down?** The two answers are deliberately opposite, and that is the
whole design.

* **Rate limiting fails open.** Redis being unavailable must not take down the
  customer's login flow. The limiter exists to protect us from bursts, and
  during a Redis outage we would rather absorb a burst than manufacture a total
  outage. Logged loudly so it is visible rather than silent.
* **Idempotency fails closed-ish** — it degrades to *no* deduplication and says
  so. Pretending a request is new is the safe direction: at worst the caller is
  charged twice for a retry, which is recoverable. Serving a stale cached
  response we cannot validate is not.

The bucket is refilled lazily rather than by a timer. A Lua script does the
read-refill-consume in one round trip, which is what makes it atomic — the
read-modify-write version has a race that lets N concurrent callers each see the
same remaining count and all pass.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import structlog
from redis.exceptions import RedisError

from app.core.redis import get_redis

logger = structlog.get_logger(__name__)

# KEYS[1] = bucket key
# ARGV    = capacity, refill_per_second, now_ms, cost, ttl_seconds
#
# Returns {allowed, remaining, retry_after_ms}. Doing this in Lua rather than in
# Python is not an optimisation — it is the correctness requirement. Redis runs
# the script atomically, so two concurrent requests cannot both read the same
# token count and both decide they are under the limit.
_BUCKET_LUA = """
local key      = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill   = tonumber(ARGV[2])
local now_ms   = tonumber(ARGV[3])
local cost     = tonumber(ARGV[4])
local ttl      = tonumber(ARGV[5])

local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts     = tonumber(state[2])

if tokens == nil then
  tokens = capacity
  ts = now_ms
end

-- Lazy refill: credit whatever has accrued since the last call.
local elapsed = math.max(0, now_ms - ts) / 1000.0
tokens = math.min(capacity, tokens + elapsed * refill)

local allowed = 0
local retry_after_ms = 0

if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  local deficit = cost - tokens
  retry_after_ms = math.ceil((deficit / refill) * 1000)
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now_ms)
redis.call('EXPIRE', key, ttl)

return {allowed, math.floor(tokens), retry_after_ms}
"""


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int
    # True when Redis was unreachable and the request was let through. Surfaced
    # so a caller can log it and a test can assert on it, rather than a silent
    # bypass that looks identical to being under the limit.
    degraded: bool = False

    def headers(self) -> dict[str, str]:
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(self.retry_after_seconds),
        }
        if not self.allowed:
            headers["Retry-After"] = str(max(1, self.retry_after_seconds))
        return headers


async def consume(
    key: str,
    *,
    capacity: int,
    refill_per_second: float,
    cost: int = 1,
) -> RateLimitResult:
    """Take `cost` tokens from `key`'s bucket."""
    now_ms = int(time.time() * 1000)
    # Long enough that an idle bucket refills completely before it expires, so
    # expiry can never hand someone a *smaller* allowance than they had earned.
    ttl = max(60, int(capacity / max(refill_per_second, 0.001)) * 2)

    try:
        raw = await get_redis().eval(
            _BUCKET_LUA,
            1,
            key,
            capacity,
            refill_per_second,
            now_ms,
            cost,
            ttl,
        )
    except RedisError as exc:
        logger.warning("rate_limit_degraded", key=key, error=str(exc))
        return RateLimitResult(
            allowed=True,
            limit=capacity,
            remaining=capacity,
            retry_after_seconds=0,
            degraded=True,
        )

    allowed, remaining, retry_after_ms = (int(value) for value in raw)
    return RateLimitResult(
        allowed=bool(allowed),
        limit=capacity,
        remaining=remaining,
        # Ceil to whole seconds: a `Retry-After: 0` invites an immediate retry
        # that is guaranteed to fail.
        retry_after_seconds=max(0, -(-retry_after_ms // 1000)),
    )


# ── Idempotency ───────────────────────────────────────────────────────────────

# 24 hours, matching the documented contract (docs/07-api-design.md §2). Long
# enough to cover any sane client retry policy, short enough that a key reused
# months later by a different request body is not silently answered from cache.
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60


def idempotency_key(organization_id: str, scope: str, key: str) -> str:
    """Namespaced so two tenants using the same key string never collide."""
    return f"idem:{organization_id}:{scope}:{key}"


async def get_cached_response(cache_key: str) -> dict[str, Any] | None:
    """The stored response for a previously-seen key, if any."""
    try:
        raw = await get_redis().get(cache_key)
    except RedisError as exc:
        # Degrade to "not seen before". The caller re-runs the operation, which
        # may double-charge a retry — recoverable, and better than serving a
        # response we cannot confirm.
        logger.warning("idempotency_lookup_degraded", error=str(exc))
        return None

    if raw is None:
        return None
    try:
        body: dict[str, Any] = json.loads(raw)
        return body
    except (TypeError, ValueError):
        return None


async def store_response(cache_key: str, body: dict[str, Any]) -> None:
    try:
        await get_redis().set(
            cache_key,
            json.dumps(body, default=str),
            ex=IDEMPOTENCY_TTL_SECONDS,
            # NX so a concurrent duplicate cannot overwrite the first response.
            # Two simultaneous retries then converge on one answer instead of
            # racing to decide which one is canonical.
            nx=True,
        )
    except RedisError as exc:
        logger.warning("idempotency_store_degraded", error=str(exc))


async def claim(cache_key: str) -> bool:
    """Reserve a key before doing the work. True when this caller won.

    Guards the window between "no cached response yet" and "response stored".
    Without it, two retries arriving together both miss the cache and both run
    the pipeline — which is exactly the double-charge idempotency exists to
    prevent.
    """
    try:
        return bool(await get_redis().set(f"{cache_key}:lock", "1", ex=120, nx=True))
    except RedisError:
        # No lock available means no protection, but the operation must still
        # proceed — refusing here would make Redis a hard dependency of the
        # verification path.
        return True
