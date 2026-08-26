"""Prefixed ULID identifiers.

Every public identifier is `<prefix>_<ulid>` — for example
`sub_01HQZX8K4M2N7PQRSTVWXYZ012`.

Rationale (docs/06-database.md §1): ULIDs sort by creation time, which keeps
B-tree inserts sequential and makes IDs meaningful in logs; the prefix makes a
bare ID self-describing in a support ticket; neither property is available from
a bare UUIDv4, and neither is enumerable like a serial integer.
"""

from __future__ import annotations

from typing import Final

from ulid import ULID

# The single source of truth for ID prefixes. Mirrored in packages/shared/src/index.ts.
ORGANIZATION: Final = "org"
USER: Final = "usr"
MEMBERSHIP: Final = "mem"
INVITATION: Final = "inv"
ROLE: Final = "role"
API_KEY: Final = "ak"
SUBJECT: Final = "sub"
FACE_PROFILE: Final = "fp"
FACE_TEMPLATE: Final = "ft"
ENROLLMENT: Final = "enr"
VERIFICATION_SESSION: Final = "vs"
AUDIT_LOG: Final = "aud"
WEBHOOK_ENDPOINT: Final = "whe"
WEBHOOK_DELIVERY: Final = "whd"
REQUEST: Final = "req"


def new_id(prefix: str) -> str:
    """Generate a prefixed ULID."""
    return f"{prefix}_{ULID()}"


def id_factory(prefix: str):  # type: ignore[no-untyped-def]
    """Return a zero-argument callable for SQLAlchemy `default=`."""

    def _factory() -> str:
        return new_id(prefix)

    return _factory


def parse_prefix(identifier: str) -> str | None:
    """Return the prefix of an identifier, or None if it is not prefixed."""
    prefix, separator, _ = identifier.partition("_")
    return prefix if separator else None


def has_prefix(identifier: str, prefix: str) -> bool:
    """Check that an identifier carries the expected prefix.

    Used at API boundaries to reject an ID of the wrong type before it reaches
    the database — a cheap way to turn a confusing 404 into a clear 400.
    """
    return identifier.startswith(f"{prefix}_")
