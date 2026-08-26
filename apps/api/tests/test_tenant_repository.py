"""Tenant isolation at the repository layer.

Shared-schema multi-tenancy lives or dies on the tenant filter never being
forgotten. These tests assert the guarantee is structural — that the base class
injects the filter and refuses to be misused — rather than something a reviewer
has to catch.

From Phase 3 this is joined by a generated suite that drives every HTTP
endpoint across a tenant boundary and asserts a 404.
"""

from __future__ import annotations

import pytest
from sqlalchemy import String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.exceptions import BadRequestError, NotFoundError
from app.shared.base_model import Base, IDMixin, SoftDeleteMixin, TimestampMixin
from app.shared.base_repository import (
    TenantScopedRepository,
    decode_cursor,
    encode_cursor,
)

ORG_A = "org_aaaaaaaaaaaaaaaaaaaaaaaaaa"
ORG_B = "org_bbbbbbbbbbbbbbbbbbbbbbbbbb"


class Widget(Base, IDMixin, TimestampMixin, SoftDeleteMixin):
    """A stand-in for any tenant-owned entity. Test-only."""

    __id_prefix__ = "wgt"

    organization_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class GlobalThing(Base, IDMixin, TimestampMixin):
    """A global (non-tenant) table. Test-only."""

    name: Mapped[str] = mapped_column(String(100), nullable=False)


class WidgetRepository(TenantScopedRepository[Widget]):
    model = Widget


class BrokenRepository(TenantScopedRepository[GlobalThing]):
    model = GlobalThing


# ── Structural guarantees ─────────────────────────────────────────────────────


def test_repository_rejects_a_model_without_organization_id() -> None:
    """The mistake is caught at construction, not at query time."""
    with pytest.raises(TypeError, match="has no organization_id"):
        BrokenRepository(session=None, organization_id=ORG_A)  # type: ignore[arg-type]


def test_repository_requires_an_organization_id() -> None:
    with pytest.raises(ValueError, match="organization_id is required"):
        WidgetRepository(session=None, organization_id="")  # type: ignore[arg-type]


def test_scoped_query_always_carries_the_tenant_filter() -> None:
    repository = WidgetRepository(session=None, organization_id=ORG_A)  # type: ignore[arg-type]

    compiled = str(repository._scoped().compile(compile_kwargs={"literal_binds": True}))

    assert f"organization_id = '{ORG_A}'" in compiled
    assert "deleted_at IS NULL" in compiled


# ── Behaviour ─────────────────────────────────────────────────────────────────


async def test_reads_are_confined_to_the_tenant(session: AsyncSession) -> None:
    repo_a = WidgetRepository(session, ORG_A)
    repo_b = WidgetRepository(session, ORG_B)

    widget_a = await repo_a.create(name="belongs to A")
    await repo_b.create(name="belongs to B")
    await session.commit()

    assert await repo_a.count() == 1
    assert await repo_b.count() == 1

    # The other tenant's row is invisible, not forbidden.
    assert await repo_b.get(widget_a.id) is None


async def test_cross_tenant_get_raises_not_found_not_forbidden(
    session: AsyncSession,
) -> None:
    """403 would confirm the row exists. 404 leaks nothing."""
    widget = await WidgetRepository(session, ORG_A).create(name="secret")
    await session.commit()

    with pytest.raises(NotFoundError):
        await WidgetRepository(session, ORG_B).get_or_404(widget.id)


async def test_create_overrides_a_forged_organization_id(session: AsyncSession) -> None:
    """A caller must not be able to write into another tenant."""
    repository = WidgetRepository(session, ORG_A)

    widget = await repository.create(name="forged", organization_id=ORG_B)
    await session.commit()

    assert widget.organization_id == ORG_A


async def test_update_cannot_move_a_row_between_tenants(session: AsyncSession) -> None:
    repository = WidgetRepository(session, ORG_A)
    widget = await repository.create(name="original")
    await session.commit()

    await repository.update(widget, name="renamed", organization_id=ORG_B)
    await session.commit()

    assert widget.name == "renamed"
    assert widget.organization_id == ORG_A


async def test_soft_deleted_rows_disappear_from_reads(session: AsyncSession) -> None:
    repository = WidgetRepository(session, ORG_A)
    widget = await repository.create(name="temporary")
    await session.commit()

    await repository.soft_delete(widget)
    await session.commit()

    assert await repository.get(widget.id) is None
    assert await repository.count() == 0
    assert widget.is_deleted


async def test_hard_delete_removes_the_row(session: AsyncSession) -> None:
    """The only correct option for biometric templates."""
    repository = WidgetRepository(session, ORG_A)
    widget = await repository.create(name="gone")
    await session.commit()

    await repository.hard_delete(widget)
    await session.commit()

    assert await repository.count() == 0


async def test_ids_are_prefixed(session: AsyncSession) -> None:
    widget = await WidgetRepository(session, ORG_A).create(name="x")
    assert widget.id.startswith("wgt_")


async def test_table_name_is_derived_from_the_class(session: AsyncSession) -> None:
    assert Widget.__tablename__ == "widgets"


# ── Pagination ────────────────────────────────────────────────────────────────


async def test_pagination_walks_every_row_without_repeats(
    session: AsyncSession,
) -> None:
    repository = WidgetRepository(session, ORG_A)
    for index in range(25):
        await repository.create(name=f"widget-{index:02d}")
    await session.commit()

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):  # bounded so a bug cannot hang the suite
        page = await repository.paginate(cursor=cursor, limit=10)
        seen.extend(widget.id for widget in page.items)
        if not page.has_more:
            break
        cursor = page.next_cursor

    assert len(seen) == 25
    assert len(set(seen)) == 25, "cursor pagination returned a duplicate"


async def test_page_size_is_capped(session: AsyncSession) -> None:
    repository = WidgetRepository(session, ORG_A)
    page = await repository.paginate(limit=10_000)
    assert page.limit == 100


async def test_cursor_roundtrip() -> None:
    assert decode_cursor(encode_cursor("wgt_123")) == "wgt_123"


async def test_cursor_is_opaque_to_clients() -> None:
    """Base64 signals 'do not parse this' and keeps the payload changeable."""
    assert "wgt_123" not in encode_cursor("wgt_123")


@pytest.mark.parametrize("cursor", ["not-a-real-cursor!!", "", "e30", "eyJ4IjogMX0"])
async def test_malformed_cursor_is_a_client_error(cursor: str) -> None:
    """A bad cursor is the caller's mistake — 400, never a 500."""
    with pytest.raises(BadRequestError):
        decode_cursor(cursor)


async def test_pagination_orders_newest_first(session: AsyncSession) -> None:
    """ULIDs sort by creation time, so id DESC is newest-first for free."""
    repository = WidgetRepository(session, ORG_A)
    for index in range(5):
        await repository.create(name=f"widget-{index}")
    await session.commit()

    page = await repository.paginate(limit=5)

    names = [widget.name for widget in page.items]
    assert names == ["widget-4", "widget-3", "widget-2", "widget-1", "widget-0"]


async def test_pagination_does_not_leak_across_tenants(session: AsyncSession) -> None:
    repo_a = WidgetRepository(session, ORG_A)
    repo_b = WidgetRepository(session, ORG_B)
    for index in range(5):
        await repo_a.create(name=f"a-{index}")
        await repo_b.create(name=f"b-{index}")
    await session.commit()

    page = await repo_a.paginate(limit=100)

    assert len(page.items) == 5
    assert all(widget.name.startswith("a-") for widget in page.items)
