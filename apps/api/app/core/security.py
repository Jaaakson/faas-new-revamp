"""Cryptographic primitives.

Three distinct problems, three different tools — matched to input entropy and
where each sits on the latency budget (docs/09-security.md §2):

* **Passwords** — low entropy, attacker-guessable, verified once per login.
  Argon2id, memory-hard, deliberately slow.
* **API keys and opaque tokens** — ~190 bits of random, no dictionary to attack,
  verified on the hot path of every request. SHA-256, constant-time compare.
  A slow hash here would buy nothing and cost an eighth of the latency budget.
* **JWTs** — short-lived, signed, never stored.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings

TokenType = Literal["access"]

_hasher = PasswordHasher(
    time_cost=settings.ARGON2_TIME_COST,
    memory_cost=settings.ARGON2_MEMORY_COST,
    parallelism=settings.ARGON2_PARALLELISM,
)

MIN_PASSWORD_LENGTH = 12

# The passwords that survive a length requirement by being long but obvious.
# A full breach-corpus check (k-anonymity against HIBP) is the roadmap answer;
# this catches the cases a 12-character minimum alone would let through.
_COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "password",
        "password1",
        "password123",
        "passw0rd123",
        "123456789012",
        "qwertyuiop123",
        "administrator",
        "letmein12345",
        "welcome12345",
        "iloveyou1234",
        "changeme1234",
        "trustno1234567",
        "monkey123456",
        "dragon123456",
        "football1234",
        "baseball1234",
        "superman1234",
        "sunshine1234",
        "princess1234",
        "qwerty123456",
        "abc123456789",
        "111111111111",
        "000000000000",
        "aaaaaaaaaaaa",
    }
)


# ── Passwords ─────────────────────────────────────────────────────────────────


class PasswordPolicyError(ValueError):
    """Raised when a password fails policy. Message is safe to show a user."""


def validate_password(password: str, *, email: str | None = None) -> None:
    """Enforce the password policy, or raise with an actionable message.

    No composition rules (one upper, one digit, one symbol) on purpose: they are
    well documented to push people toward predictable patterns like
    `Password1!` while adding little real entropy. Length plus a common-password
    check is the stronger and less annoying policy.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > 128:
        # Not a security limit — a guard against a multi-megabyte body being fed
        # to a deliberately slow hash.
        raise PasswordPolicyError("Password must be at most 128 characters.")

    lowered = password.lower()
    if lowered in _COMMON_PASSWORDS:
        raise PasswordPolicyError("That password is too common. Choose something less predictable.")
    if email and lowered.startswith(email.split("@")[0].lower()[:8]):
        raise PasswordPolicyError("Password must not start with your email address.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password.

    Returns False rather than raising: a malformed stored hash and a wrong
    password are the same outcome to the caller, and letting one of them raise
    would turn a bad row into a 500 that discloses which accounts are broken.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Exception:
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the hash predates the current Argon2 parameters.

    Lets cost parameters be raised over time and applied transparently on the
    next successful login, without a mass reset.
    """
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# ── Opaque tokens ─────────────────────────────────────────────────────────────


def generate_token(length: int = 32) -> str:
    """A URL-safe random secret. ~190 bits at the default length."""
    return secrets.token_urlsafe(length)


def hash_token(token: str) -> str:
    """SHA-256 of a high-entropy token.

    Correct here precisely because the input is random: there is no dictionary
    to attack, so a slow hash protects against nothing while costing latency on
    every request that verifies one.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(token: str, token_hash: str) -> bool:
    """Constant-time comparison.

    A plain `==` short-circuits on the first differing byte, leaking the correct
    prefix through response timing.
    """
    return hmac.compare_digest(hash_token(token), token_hash)


# ── JWT ───────────────────────────────────────────────────────────────────────


class TokenError(Exception):
    """Raised when a JWT is missing, malformed, expired, or of the wrong type."""


def create_access_token(
    *,
    user_id: str,
    organization_id: str | None,
    role: str | None,
    expires_in_minutes: int | None = None,
) -> tuple[str, datetime]:
    """Issue a short-lived access token.

    Carries the active organization and role so the common authorization path
    needs no database round-trip. The cost of that choice is a token that is
    stale for at most 15 minutes after a role change — acceptable, and the
    reason the lifetime is short. Anything destructive re-checks the database.
    """
    now = datetime.now(tz=UTC)
    lifetime = timedelta(minutes=expires_in_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    expires_at = now + lifetime

    payload: dict[str, Any] = {
        "sub": user_id,
        "org": organization_id,
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": secrets.token_urlsafe(12),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify and decode an access token, or raise TokenError."""
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("The access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("The access token is invalid.") from exc

    # Reject a token minted for another purpose. Without this check, any signed
    # payload would be accepted as an access token.
    if payload.get("type") != "access":
        raise TokenError("The access token is invalid.")

    return payload
