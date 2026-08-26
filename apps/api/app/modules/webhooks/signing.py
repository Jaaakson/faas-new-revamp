"""Webhook signatures.

HMAC-SHA256 over `{timestamp}.{raw_body}`, in a `Fvas-Signature` header:

    Fvas-Signature: t=1753859051,v1=5257a869e7ec...

Three decisions, each closing a specific attack:

* **The timestamp is inside the signed payload.** Signing the body alone lets an
  attacker who captures one request replay it forever — the signature stays
  valid because the body never changes. Binding the time into the MAC means a
  replay has to forge a new signature.
* **Receivers reject anything older than five minutes.** The timestamp only
  helps if somebody checks it, so `verify` enforces the window rather than
  leaving it as advice in the docs.
* **Comparison is constant-time.** A byte-by-byte `==` leaks how much of a
  forged signature was correct, which is enough to reconstruct one.

`verify` exists so our own tests can act as a real receiver, and so the
documented verification snippet is executable rather than aspirational.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

SIGNATURE_HEADER = "Fvas-Signature"
EVENT_ID_HEADER = "Fvas-Event-Id"
EVENT_TYPE_HEADER = "Fvas-Event-Type"

# How stale a signed request may be before a receiver must reject it.
TOLERANCE_SECONDS = 300

SECRET_PREFIX = "whsec_"  # noqa: S105 - a namespace marker, not a secret


def generate_secret() -> str:
    """A new endpoint signing secret. 32 bytes of entropy, prefixed."""
    return f"{SECRET_PREFIX}{secrets.token_urlsafe(32)}"


def sign(payload: str, secret: str, *, timestamp: int | None = None) -> str:
    """Build the header value for `payload`."""
    issued = timestamp if timestamp is not None else int(time.time())
    signature = _digest(issued, payload, secret)
    return f"t={issued},v1={signature}"


def verify(
    payload: str,
    header: str,
    secret: str,
    *,
    tolerance_seconds: int = TOLERANCE_SECONDS,
    now: int | None = None,
) -> bool:
    """Check a signature the way a receiver should.

    Returns False rather than raising for every failure mode — a receiver
    distinguishing "malformed" from "wrong key" in its response would hand an
    attacker an oracle.
    """
    parsed = _parse(header)
    if parsed is None:
        return False
    issued, provided = parsed

    current = now if now is not None else int(time.time())
    # Both directions. A far-future timestamp is as suspicious as a stale one,
    # and clock skew large enough to matter is a configuration problem.
    if abs(current - issued) > tolerance_seconds:
        return False

    expected = _digest(issued, payload, secret)
    return hmac.compare_digest(expected, provided)


def _digest(timestamp: int, payload: str, secret: str) -> str:
    signed = f"{timestamp}.{payload}".encode()
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def _parse(header: str) -> tuple[int, str] | None:
    timestamp: int | None = None
    signature: str | None = None

    for part in header.split(","):
        key, separator, value = part.strip().partition("=")
        if not separator:
            return None
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                return None
        elif key == "v1":
            signature = value

    if timestamp is None or not signature:
        return None
    return timestamp, signature
