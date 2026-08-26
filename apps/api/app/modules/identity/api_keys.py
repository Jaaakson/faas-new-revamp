"""API key minting, verification, and lifecycle.

Format: `fvas_{env}_{32 url-safe chars}` — about 190 bits from
`secrets.token_urlsafe`. The prefix is human-readable on purpose: a key pasted
into a bug report is immediately identifiable as ours and as test-or-live, and
secret scanners can match on it.

**The secret exists exactly once, in the response that creates it.** Only a
SHA-256 digest, a lookup prefix, and the last four characters are stored, so a
database dump contains nothing that authenticates.

Three details here are security properties, not style:

* **Digest comparison is constant-time.** A plain `==` on a digest leaks how many
  leading bytes matched through timing, which is enough to reconstruct a valid
  hash byte by byte. `hmac.compare_digest` does not.
* **Revocation is checked at verification, never cached.** A revoked key must
  stop working on the *next* request, not when some TTL expires.
* **SHA-256, not Argon2.** Justified by input entropy: there is no dictionary to
  attack on 190 random bits, and a slow KDF would add ~100 ms to every call on
  the hottest path in the product. A user-chosen password is the opposite trade
  and uses Argon2id (docs/05-architecture.md §6).
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission, Role, permissions_for
from app.modules.identity.models import ApiKey

logger = structlog.get_logger(__name__)

KEY_NAMESPACE = "fvas"
SECRET_LENGTH = 32
# `fvas_live_` plus the first 8 characters of the secret. Long enough to be
# unique in practice, short enough to be safe to log and display.
PREFIX_SECRET_CHARS = 8

# How long a rotated key keeps working. A deploy that has to be finished inside
# five minutes is a deploy that will fail at 3am; a day is long enough for a
# human to roll it out and short enough that a leaked old key is not immortal.
ROTATION_OVERLAP = timedelta(hours=24)

# Scopes a key may hold. A strict subset of the permission enum: a key is a
# machine credential for the public API, so it can never reach organization
# settings, members, billing, or other keys. That containment is the entire
# reason the console and the public API are separate planes.
GRANTABLE_SCOPES: frozenset[Permission] = frozenset(
    {
        Permission.SUBJECT_READ,
        Permission.SUBJECT_WRITE,
        Permission.SUBJECT_DELETE,
        Permission.ENROLLMENT_WRITE,
        Permission.VERIFICATION_WRITE,
        Permission.VERIFICATION_READ,
    }
)

DEFAULT_SCOPES: tuple[str, ...] = (
    Permission.SUBJECT_READ.value,
    Permission.SUBJECT_WRITE.value,
    Permission.ENROLLMENT_WRITE.value,
    Permission.VERIFICATION_WRITE.value,
    Permission.VERIFICATION_READ.value,
)


@dataclass(frozen=True, slots=True)
class MintedKey:
    """A newly created key. `secret` is returned once and never again."""

    api_key: ApiKey
    secret: str


class ApiKeyError(Exception):
    """Verification failed. Carries a reason for logging, never for the caller.

    The client always sees the same generic message: distinguishing "no such
    key" from "revoked" from "expired" tells an attacker which of their guesses
    was a real key.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def generate_secret(environment: str) -> tuple[str, str, str, str]:
    """Mint a secret. Returns (secret, prefix, digest, last4)."""
    if environment not in {"test", "live"}:
        raise ValueError("environment must be 'test' or 'live'")

    body = secrets.token_urlsafe(SECRET_LENGTH)[:SECRET_LENGTH]
    secret = f"{KEY_NAMESPACE}_{environment}_{body}"
    prefix = f"{KEY_NAMESPACE}_{environment}_{body[:PREFIX_SECRET_CHARS]}"
    return secret, prefix, hash_secret(secret), body[-4:]


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def parse_prefix(secret: str) -> str | None:
    """Extract the lookup prefix from a presented secret.

    Returns None for anything not shaped like one of our keys, so a malformed
    header is rejected before it reaches the database.
    """
    # `maxsplit=2`, not a plain split. `secrets.token_urlsafe` draws from the
    # URL-safe base64 alphabet, which includes `_` — so roughly 45% of secrets
    # contain one in the body and a three-way split would shred them. Caught by
    # a test that minted a key and immediately failed to authenticate with it.
    parts = secret.split("_", 2)
    if len(parts) != 3 or parts[0] != KEY_NAMESPACE or parts[1] not in {"test", "live"}:
        return None
    body = parts[2]
    if len(body) < PREFIX_SECRET_CHARS:
        return None
    return f"{parts[0]}_{parts[1]}_{body[:PREFIX_SECRET_CHARS]}"


def normalise_scopes(requested: list[str] | None, *, role: Role) -> list[str]:
    """Intersect what was asked for with what the creator may actually delegate.

    Two bounds, both necessary. `GRANTABLE_SCOPES` stops a key ever reaching the
    console-only surface. The creator's own role stops a Developer minting a key
    that can delete subjects when they cannot — a key must never be a
    privilege-escalation path around RBAC.
    """
    holder = permissions_for(role)
    allowed = {scope.value for scope in GRANTABLE_SCOPES if scope in holder}

    if requested is None:
        return sorted(allowed & set(DEFAULT_SCOPES))

    asked = set(requested)
    unknown = asked - {scope.value for scope in GRANTABLE_SCOPES}
    if unknown:
        raise ValueError(f"unknown or non-grantable scopes: {', '.join(sorted(unknown))}")

    granted = asked & allowed
    if not granted:
        raise ValueError("none of the requested scopes are available to your role")
    return sorted(granted)


def is_usable(key: ApiKey, *, now: datetime | None = None) -> str | None:
    """None when the key may authenticate, otherwise the reason it may not."""
    moment = now or datetime.now(tz=UTC)

    if key.revoked_at is not None and key.revoked_at <= moment:
        return "revoked"
    if key.expires_at is not None and key.expires_at <= moment:
        return "expired"
    if key.rotated_at is not None and key.rotated_at + ROTATION_OVERLAP <= moment:
        # Rotated and past its grace period. Distinct from `revoked` in the log
        # because it means the customer's deploy did not finish, not that
        # someone is using a key they should not have.
        return "rotation_overlap_elapsed"
    return None


def ip_is_allowed(key: ApiKey, address: str | None) -> bool:
    """Check a caller's address against the key's CIDR allowlist.

    An unset allowlist allows everything — the feature is opt-in, and defaulting
    to deny would lock out every existing integration the moment the column was
    added.

    A key *with* an allowlist and a caller we cannot identify is denied. Failing
    open there would make the control trivially bypassable behind a proxy that
    strips the address.
    """
    if not key.ip_allowlist:
        return True
    if not address:
        return False

    try:
        caller = ipaddress.ip_address(address)
    except ValueError:
        return False

    for entry in key.ip_allowlist.split(","):
        candidate = entry.strip()
        if not candidate:
            continue
        try:
            if caller in ipaddress.ip_network(candidate, strict=False):
                return True
        except ValueError:
            # A malformed allowlist entry is ignored rather than fatal: one bad
            # row must not lock a customer out of their own API.
            logger.warning("api_key_bad_cidr", api_key_id=key.id, entry=candidate)
    return False


async def verify(
    session: AsyncSession,
    presented: str,
    *,
    ip_address: str | None = None,
) -> ApiKey:
    """Resolve a presented secret to its key, or raise `ApiKeyError`.

    One indexed lookup, then one constant-time comparison. Nothing is cached:
    revocation has to take effect on the very next request.
    """
    prefix = parse_prefix(presented)
    if prefix is None:
        raise ApiKeyError("malformed")

    key = await session.scalar(select(ApiKey).where(ApiKey.key_prefix == prefix))
    if key is None:
        # Hash anyway. Skipping the work here would make a nonexistent key
        # measurably faster to reject than a wrong one, turning the endpoint
        # into an oracle for which prefixes exist.
        hmac.compare_digest(hash_secret(presented), hash_secret("decoy"))
        raise ApiKeyError("unknown_prefix")

    if not hmac.compare_digest(key.key_hash, hash_secret(presented)):
        raise ApiKeyError("bad_secret")

    unusable = is_usable(key)
    if unusable is not None:
        raise ApiKeyError(unusable)

    if not ip_is_allowed(key, ip_address):
        raise ApiKeyError("ip_not_allowed")

    return key


def mint(
    *,
    organization_id: str,
    name: str,
    environment: str,
    scopes: list[str],
    created_by_user_id: str | None,
    expires_at: datetime | None = None,
    ip_allowlist: str | None = None,
) -> MintedKey:
    secret, prefix, digest, last4 = generate_secret(environment)
    return MintedKey(
        api_key=ApiKey(
            organization_id=organization_id,
            name=name,
            environment=environment,
            key_prefix=prefix,
            key_hash=digest,
            last4=last4,
            scopes=scopes,
            created_by_user_id=created_by_user_id,
            expires_at=expires_at,
            # Only live keys accept an allowlist. A test key is expected to be
            # used from a laptop on a changing address, and silently applying a
            # restriction there would look like the key is broken.
            ip_allowlist=ip_allowlist if environment == "live" else None,
        ),
        secret=secret,
    )
