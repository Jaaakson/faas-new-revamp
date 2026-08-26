"""Tenant-scoped data access.

This class is the structural half of the multi-tenancy guarantee
(docs/05-architecture.md §5). Shared-schema tenancy fails when someone forgets
a `WHERE organization_id = ...`, so the filter is not something a query author
remembers — it is injected by the only base class tenant repositories may use,
and every read path goes through `_scoped()`.

Three further layers back this up: composite indexes leading with
`organization_id`, generated cross-tenant tests over every endpoint, and
Postgres RLS (Phase 8). Code review is not an isolation mechanism.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.exceptions import BadRequestError, NotFoundError
from app.shared.base_model import Base

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


def encode_cursor(identifier: str) -> str:
    """Opaque cursor over the ULID primary key.

    The key is the ID alone, not (created_at, id). A ULID's leading 48 bits are
    a millisecond timestamp, so lexicographic order *is* creation order — the
    property the ID scheme was chosen for (docs/06-database.md §1). Keying on it
    directly means the keyset rides the primary key index, needs no composite
    index, and is immune to two real problems that a `created_at` key has:
    second-granularity clocks (every row in a burst shares a timestamp) and
    databases that compare timestamps as strings.

    Base64 signals "do not parse this" to clients and leaves us free to change
    the payload without a breaking API change.
    """
    payload = json.dumps({"i": identifier})
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> str:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        identifier = payload["i"]
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("cursor payload is missing an identifier")
        return identifier
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise BadRequestError(
            "The pagination cursor is malformed.",
            code="invalid_cursor",
        ) from exc


class Page[ModelT: Base]:
    """One page of results plus the cursor for the next."""

    __slots__ = ("has_more", "items", "limit", "next_cursor")

    def __init__(
        self,
        items: list[ModelT],
        next_cursor: str | None,
        has_more: bool,
        limit: int,
    ) -> None:
        self.items = items
        self.next_cursor = next_cursor
        self.has_more = has_more
        self.limit = limit


class TenantScopedRepository[ModelT: Base]:
    """Base class for every repository over a tenant-owned table.

    A repository is private to its module: cross-module access goes through the
    other module's service, never its repository (docs/05-architecture.md §2).
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession, organization_id: str) -> None:
        # Fail at construction, not at query time. A model without
        # organization_id is not tenant-owned and must not use this base class —
        # catching that here makes the mistake impossible to ship.
        if not hasattr(self.model, "organization_id"):
            raise TypeError(
                f"{self.model.__name__} has no organization_id column and cannot use "
                "TenantScopedRepository. Use a plain repository for global tables."
            )
        if not organization_id:
            raise ValueError("organization_id is required for a tenant-scoped repository")

        self.session = session
        self.organization_id = organization_id

    # ── Query construction ────────────────────────────────────────────────────

    def _scoped(self) -> Select[tuple[ModelT]]:
        """The only sanctioned entry point for building a query.

        Every read in a tenant repository starts here. A query built any other
        way does not carry the tenant filter and should not pass review.
        """
        statement = select(self.model).where(
            self.model.organization_id == self.organization_id  # type: ignore[attr-defined]
        )
        # Soft-deleted rows are invisible unless a caller explicitly asks.
        if hasattr(self.model, "deleted_at"):
            statement = statement.where(
                self.model.deleted_at.is_(None)  # type: ignore[attr-defined]
            )
        return statement

    def _scoped_including_deleted(self) -> Select[tuple[ModelT]]:
        return select(self.model).where(
            self.model.organization_id == self.organization_id  # type: ignore[attr-defined]
        )

    # ── Reads ─────────────────────────────────────────────────────────────────

    async def get(self, identifier: str) -> ModelT | None:
        result = await self.session.execute(
            self._scoped().where(self.model.id == identifier)  # type: ignore[attr-defined]
        )
        return result.scalar_one_or_none()

    async def get_or_404(self, identifier: str) -> ModelT:
        """Fetch or raise.

        A row belonging to another tenant is indistinguishable from a row that
        does not exist — returning 403 here would confirm existence across the
        tenant boundary (docs/07-api-design.md §2).
        """
        instance = await self.get(identifier)
        if instance is None:
            raise NotFoundError(
                f"{self.model.__name__} '{identifier}' was not found.",
                details={"resource": self.model.__name__.lower(), "id": identifier},
            )
        return instance

    async def exists(self, identifier: str) -> bool:
        result = await self.session.execute(
            select(func.count())
            .select_from(self.model)
            .where(
                self.model.id == identifier,  # type: ignore[attr-defined]
                self.model.organization_id == self.organization_id,  # type: ignore[attr-defined]
            )
        )
        return (result.scalar_one() or 0) > 0

    async def count(self, *filters: ColumnElement[bool]) -> int:
        statement = (
            select(func.count())
            .select_from(self.model)
            .where(
                self.model.organization_id == self.organization_id  # type: ignore[attr-defined]
            )
        )
        if hasattr(self.model, "deleted_at"):
            statement = statement.where(
                self.model.deleted_at.is_(None)  # type: ignore[attr-defined]
            )
        for condition in filters:
            statement = statement.where(condition)
        result = await self.session.execute(statement)
        return int(result.scalar_one() or 0)

    async def paginate(
        self,
        *filters: ColumnElement[bool],
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Page[ModelT]:
        """Cursor pagination, newest first, keyed on the ULID primary key.

        Offset pagination would skip and duplicate rows on tables that receive
        continuous inserts — which describes every log table in this system.
        """
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        statement = self._scoped()
        for condition in filters:
            statement = statement.where(condition)

        if cursor:
            statement = statement.where(
                self.model.id < decode_cursor(cursor)  # type: ignore[attr-defined]
            )

        statement = statement.order_by(
            self.model.id.desc()  # type: ignore[attr-defined]
        ).limit(limit + 1)  # one extra row answers has_more without a second query

        result = await self.session.execute(statement)
        rows = list(result.scalars().all())

        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = (
            encode_cursor(items[-1].id)  # type: ignore[attr-defined]
            if has_more and items
            else None
        )
        return Page(items=items, next_cursor=next_cursor, has_more=has_more, limit=limit)

    # ── Writes ────────────────────────────────────────────────────────────────

    async def create(self, **values: Any) -> ModelT:
        """Insert a row, forcing the tenant.

        `organization_id` is overwritten rather than merged: a caller must not
        be able to write into another tenant by passing it explicitly.
        """
        values["organization_id"] = self.organization_id
        instance = self.model(**values)
        self.session.add(instance)
        await self.session.flush()  # assign defaults; the service commits
        return instance

    async def update(self, instance: ModelT, **values: Any) -> ModelT:
        values.pop("organization_id", None)  # tenant is immutable
        values.pop("id", None)
        for field, value in values.items():
            setattr(instance, field, value)
        await self.session.flush()
        return instance

    async def soft_delete(self, instance: ModelT) -> ModelT:
        if not hasattr(instance, "deleted_at"):
            raise TypeError(
                f"{type(instance).__name__} has no deleted_at column; use hard_delete()."
            )
        # mypy narrows `instance` through the hasattr check above.
        instance.deleted_at = datetime.now(tz=UTC)
        await self.session.flush()
        return instance

    async def hard_delete(self, instance: ModelT) -> None:
        """Physically remove a row.

        The correct and only option for biometric templates.
        """
        await self.session.delete(instance)
        await self.session.flush()
