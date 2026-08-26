"""Declarative base and the mixins every table uses."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column
from sqlalchemy.types import TypeDecorator

from app.shared.utils.ids import new_id


class UTCDateTime(TypeDecorator[datetime]):
    """A timestamp that is always timezone-aware UTC in Python.

    A plain timezone-aware DateTime is honoured by Postgres but ignored by
    SQLite, which returns naive datetimes. Mixing the two raises
    "can't compare offset-naive and offset-aware datetimes" — at runtime, in
    whichever comparison happens to run first, on whichever backend differs.

    Normalising in the type removes the entire class of bug: every value written
    is converted to UTC, and every value read comes back aware, on any backend.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        if value.tzinfo is None:
            # A naive value reaching the database is a bug upstream, but
            # assuming UTC is far better than storing an ambiguous instant.
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    """Declarative base for every model.

    Table names are derived from the class name, so `FaceProfile` becomes
    `face_profiles` without a per-model `__tablename__`. One convention, applied
    automatically, cannot drift.
    """

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()
        # Naive pluralization is sufficient for this schema and is overridable.
        if snake.endswith(("s", "x", "z", "ch", "sh")):
            return f"{snake}es"
        if snake.endswith("y") and snake[-2] not in "aeiou":
            return f"{snake[:-1]}ies"
        return f"{snake}s"

    def __repr__(self) -> str:
        identifier = getattr(self, "id", None)
        return f"<{type(self).__name__} id={identifier!r}>"


class IDMixin:
    """Prefixed ULID primary key.

    Subclasses set `__id_prefix__`; see app.shared.utils.ids for the registry.
    """

    __id_prefix__: str = "id"

    @declared_attr
    @classmethod
    def id(cls) -> Mapped[str]:
        prefix = cls.__id_prefix__
        return mapped_column(
            String(40),
            primary_key=True,
            default=lambda: new_id(prefix),
        )


class TimestampMixin:
    """Creation and update timestamps, both server-side.

    `server_default`/`onupdate` mean a row written by a migration, a seed
    script, or psql still gets correct timestamps — an application-side default
    would silently leave them null.
    """

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Soft deletion for business entities.

    Deliberately NOT used by `face_templates`: a soft-deleted biometric
    template is retained biometric data, which is exactly what a deletion
    request forbids. See docs/06-database.md §4.3.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        nullable=True,
        default=None,
        index=True,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
