"""Analytics, logs, subjects, and verification listing for the console."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.dependencies.auth import Principal, require_permission
from app.dependencies.db import get_db
from app.modules.analytics.schemas import (
    AuditLogEntry,
    AuthLogEntry,
    FailureReason,
    HourlyCell,
    LatencyDistribution,
    OutcomeSlice,
    OverviewResponse,
    Page,
    Pagination,
    SubjectListItem,
    TimeseriesPoint,
    UsageResponse,
)
from app.modules.analytics.service import AnalyticsService
from app.modules.auth.models import AuthLog
from app.modules.biometrics.models import AuditLog, Subject
from app.modules.identity.models import Organization
from app.shared.base_model import IDMixin
from app.shared.base_repository import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    decode_cursor,
    encode_cursor,
)

router = APIRouter(tags=["Analytics"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

ReadVerifications = Annotated[Principal, Depends(require_permission(Permission.VERIFICATION_READ))]
ReadSubjects = Annotated[Principal, Depends(require_permission(Permission.SUBJECT_READ))]
ReadAudit = Annotated[Principal, Depends(require_permission(Permission.AUDIT_READ))]


# Bounded on IDMixin, which is exactly the real constraint: a mapped class with
# a ULID primary key. A structural Protocol does not work here — SQLAlchemy
# types `id` as a query expression at class level and as a plain `str` on an
# instance, so no single Protocol member matches both uses.
async def _paginate[ModelT: IDMixin, SchemaT](
    session: AsyncSession,
    statement: Select[tuple[ModelT]],
    *,
    model: type[ModelT],
    cursor: str | None,
    limit: int,
    serialize: Callable[[ModelT], SchemaT],
) -> Page[SchemaT]:
    """Cursor pagination on the ULID primary key.

    The same keyset the repositories use: ULIDs sort by creation time, so
    ordering by id descending is newest-first without a composite index, and
    without the duplicate-row problem offset pagination has on a table that is
    continuously inserted into.
    """
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    if cursor:
        statement = statement.where(model.id < decode_cursor(cursor))

    statement = statement.order_by(model.id.desc()).limit(limit + 1)
    rows = list(await session.scalars(statement))

    has_more = len(rows) > limit
    items = rows[:limit]

    return Page[SchemaT](
        data=[serialize(row) for row in items],
        pagination=Pagination(
            next_cursor=encode_cursor(items[-1].id) if has_more and items else None,
            has_more=has_more,
            limit=limit,
        ),
    )


# ── Analytics ─────────────────────────────────────────────────────────────────


@router.get(
    "/analytics/overview",
    response_model=OverviewResponse,
    summary="Headline metrics with period-over-period deltas",
    description=(
        "Volume answers 'is it being used', success rate 'is it working', p95 'is it "
        "fast enough to keep', and active subjects 'is it growing'. Errors are excluded "
        "from the success-rate denominator — our incident is not the customer's "
        "verification failure."
    ),
)
async def overview(
    principal: ReadVerifications,
    session: DbSession,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> OverviewResponse:
    return await AnalyticsService(session).overview(principal.require_organization, days)


@router.get(
    "/analytics/timeseries",
    response_model=list[TimeseriesPoint],
    summary="Daily verification volume by outcome",
)
async def timeseries(
    principal: ReadVerifications,
    session: DbSession,
    days: Annotated[int, Query(ge=7, le=90)] = 30,
) -> list[TimeseriesPoint]:
    return await AnalyticsService(session).timeseries(principal.require_organization, days)


@router.get(
    "/analytics/outcomes",
    response_model=list[OutcomeSlice],
    summary="Decision split",
)
async def outcomes(
    principal: ReadVerifications,
    session: DbSession,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> list[OutcomeSlice]:
    return await AnalyticsService(session).outcomes(principal.require_organization, days)


@router.get(
    "/analytics/failure-reasons",
    response_model=list[FailureReason],
    summary="Why verifications did not succeed",
)
async def failure_reasons(
    principal: ReadVerifications,
    session: DbSession,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> list[FailureReason]:
    return await AnalyticsService(session).failure_reasons(principal.require_organization, days)


@router.get(
    "/analytics/latency",
    response_model=LatencyDistribution,
    summary="Latency distribution with p50, p95 and p99",
)
async def latency(
    principal: ReadVerifications,
    session: DbSession,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> LatencyDistribution:
    return await AnalyticsService(session).latency_distribution(
        principal.require_organization, days
    )


@router.get(
    "/analytics/hourly",
    response_model=list[HourlyCell],
    summary="Success rate by weekday and hour",
    description=(
        "Exposes physical conditions in the field: a night-shift dip is nearly always "
        "lighting, not fraud. Turns a support conversation into a product one."
    ),
)
async def hourly(
    principal: ReadVerifications,
    session: DbSession,
    days: Annotated[int, Query(ge=7, le=90)] = 30,
) -> list[HourlyCell]:
    return await AnalyticsService(session).hourly_heatmap(principal.require_organization, days)


@router.get(
    "/usage/current",
    response_model=UsageResponse,
    summary="Quota consumption for the current billing period",
)
async def usage(principal: ReadVerifications, session: DbSession) -> UsageResponse:
    organization = await session.get(Organization, principal.require_organization)
    plan = organization.plan if organization else "free"
    return await AnalyticsService(session).usage(principal.require_organization, plan)


# ── Verifications ─────────────────────────────────────────────────────────────


# Verification listing lives in the biometrics module, which owns the table
# and can join the subject to fill `subject_external_id`. A second copy here
# would shadow it on the same path and always return a null external id.


# ── Subjects ──────────────────────────────────────────────────────────────────


@router.get(
    "/subjects",
    response_model=Page[SubjectListItem],
    summary="List subjects",
)
async def list_subjects(
    principal: ReadSubjects,
    session: DbSession,
    status: str | None = None,
    search: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[SubjectListItem]:
    statement = select(Subject).where(
        Subject.organization_id == principal.require_organization,
        Subject.deleted_at.is_(None),
    )
    if status:
        statement = statement.where(Subject.status == status)
    if search:
        statement = statement.where(Subject.external_id.ilike(f"%{search}%"))

    def serialize(row: Subject) -> SubjectListItem:
        return SubjectListItem(
            id=row.id,
            external_id=row.external_id,
            display_name=row.display_name,
            status=row.status,
            verification_count=row.verification_count,
            enrolled_at=row.enrolled_at,
            last_verified_at=row.last_verified_at,
            created_at=row.created_at,
        )

    return await _paginate(
        session, statement, model=Subject, cursor=cursor, limit=limit, serialize=serialize
    )


# ── Logs ──────────────────────────────────────────────────────────────────────


@router.get(
    "/logs/audit",
    response_model=Page[AuditLogEntry],
    summary="Audit log",
    description=(
        "Every mutating action, append-only. Viewer holds `audit:read` so a compliance "
        "officer can have a genuinely read-only account."
    ),
)
async def audit_log(
    principal: ReadAudit,
    session: DbSession,
    action: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[AuditLogEntry]:
    statement = select(AuditLog).where(AuditLog.organization_id == principal.require_organization)
    if action:
        statement = statement.where(AuditLog.action == action)

    def serialize(row: AuditLog) -> AuditLogEntry:
        return AuditLogEntry(
            id=row.id,
            actor_type=row.actor_type,
            actor_email=row.actor_email,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            changes=row.changes,
            ip_address=row.ip_address,
            request_id=row.request_id,
            created_at=row.created_at,
        )

    return await _paginate(
        session, statement, model=AuditLog, cursor=cursor, limit=limit, serialize=serialize
    )


@router.get(
    "/logs/auth",
    response_model=Page[AuthLogEntry],
    summary="Authentication events for members of this organization",
    description=(
        "Scoped to the current organization's members. `auth_logs` is global — it "
        "records failed logins for addresses that belong to no tenant — so it is "
        "filtered here rather than being tenant-owned."
    ),
)
async def auth_log(
    principal: ReadAudit,
    session: DbSession,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[AuthLogEntry]:
    from app.modules.identity.models import Membership

    member_ids = select(Membership.user_id).where(
        Membership.organization_id == principal.require_organization
    )
    statement = select(AuthLog).where(AuthLog.user_id.in_(member_ids))

    def serialize(row: AuthLog) -> AuthLogEntry:
        return AuthLogEntry(
            id=row.id,
            email=row.email,
            event=row.event,
            success=row.success,
            ip_address=row.ip_address,
            user_agent=row.user_agent,
            detail=row.detail,
            created_at=row.created_at,
        )

    return await _paginate(
        session, statement, model=AuthLog, cursor=cursor, limit=limit, serialize=serialize
    )


def _iso(value: datetime) -> str:
    return value.isoformat()
