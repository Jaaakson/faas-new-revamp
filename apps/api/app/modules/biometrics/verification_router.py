"""Verification endpoints.

The ordering inside `create_verification` is the design, and each step is placed
where it is for a reason:

    rate limit → idempotency replay → quota → verify → cache → respond

Rate limiting comes first because it is the cheapest way to shed load and must
work even when everything behind it is struggling. Idempotency replay comes
before quota so a retried request cannot be charged twice. Quota comes before
the pipeline so an over-limit tenant never pays for CPU they are not allowed to
consume.

A failed verification is a `200`. "This is not the right person" is a successful
answer to the question asked; only a failed *request* is an error. Conflating
the two forces every integrator to write exception handling around a normal
business outcome.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import RateLimitedError
from app.core.permissions import Permission
from app.core.plans import get_plan
from app.core.ratelimit import (
    consume,
    get_cached_response,
    store_response,
)
from app.core.ratelimit import (
    idempotency_key as build_idempotency_key,
)
from app.dependencies.auth import Principal, require_permission
from app.dependencies.db import get_db
from app.modules.analytics.schemas import (
    SimilarityBucket,
    SimulatedFlip,
    ThresholdSimulation,
)
from app.modules.biometrics.engine.base import FaceEngine
from app.modules.biometrics.engine.registry import get_engine
from app.modules.biometrics.models import Subject, VerificationSession
from app.modules.biometrics.schemas import (
    ThresholdInfo,
    VerificationDetail,
    VerificationListItem,
    VerificationRequest,
    VerificationResponse,
)
from app.modules.biometrics.threshold import describe as describe_threshold
from app.modules.biometrics.verification import VerificationService
from app.modules.identity.models import Organization, OrgSettings
from app.shared.base_repository import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    decode_cursor,
    encode_cursor,
)
from app.shared.schemas import Page, Pagination

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Verification"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
Engine = Annotated[FaceEngine, Depends(get_engine)]

WriteVerifications = Annotated[
    Principal, Depends(require_permission(Permission.VERIFICATION_WRITE))
]
ReadVerifications = Annotated[Principal, Depends(require_permission(Permission.VERIFICATION_READ))]


@router.post(
    "/verifications",
    response_model=VerificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify a face against a subject",
    description=(
        "The core endpoint.\n\n"
        "**A rejected verification is a `200`.** `decision` carries the outcome; only a "
        "failed *request* is a `4xx`.\n\n"
        "`inconclusive` is never collapsed into `rejected` - telling someone they are not "
        "who they claim when the truth is that the room is too dark would be both wrong "
        "and would corrupt your fraud metrics with lighting problems.\n\n"
        "Send `Idempotency-Key` on retries: the first response is replayed for 24 hours "
        "without re-running the pipeline or charging quota a second time."
    ),
    responses={
        429: {"description": "Rate limit or monthly quota exhausted; carries `Retry-After`"},
    },
)
async def create_verification(
    body: VerificationRequest,
    principal: WriteVerifications,
    session: DbSession,
    request: Request,
    response: Response,
    engine: Engine,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    from app.modules.biometrics.service import Actor

    organization_id = principal.require_organization
    organization = await session.get(Organization, organization_id)
    plan = get_plan(organization.plan if organization else "free")

    # 1 · Rate limit. Cheapest possible rejection, and it must keep working when
    #     everything behind it is under strain.
    limit = await consume(
        f"rl:verify:{organization_id}",
        capacity=plan.verifications_per_second,
        refill_per_second=float(plan.verifications_per_second),
    )
    response.headers.update(limit.headers())
    if not limit.allowed:
        raise RateLimitedError(
            retry_after=limit.retry_after_seconds or 1,
            message="Too many verification requests. Slow down.",
            details={"limit_per_second": plan.verifications_per_second},
        )

    actor = Actor(
        organization_id=organization_id,
        user_id=principal.user_id,
        email=principal.email,
        source="console",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
    )
    service = VerificationService(session, actor, engine)

    # 2 · Idempotency replay, before quota. A retried network call must not be
    #     charged twice, so the replay has to short-circuit the meter as well as
    #     the pipeline.
    cache_key = (
        build_idempotency_key(organization_id, "verification", idempotency_key)
        if idempotency_key
        else None
    )
    if cache_key:
        cached = await get_cached_response(cache_key)
        if cached is not None:
            response.headers["Idempotent-Replay"] = "true"
            logger.info("verification_idempotent_replay", organization_id=organization_id)
            return cached

    # 3 · Quota. Checked before the pipeline so an over-limit tenant never
    #     consumes CPU they are not entitled to.
    quota = await service.quota_state()
    if quota.exceeded and quota.hard_stop:
        raise RateLimitedError(
            retry_after=_seconds_until_next_month(),
            message=(
                f"Monthly verification quota of {quota.limit:,} exhausted on the {quota.plan} plan."
            ),
            details={"used": quota.used, "limit": quota.limit, "plan": quota.plan},
        )

    result = await service.verify(
        subject_ref=body.subject_id,
        image=body.image,
        requested_threshold=body.options.threshold,
        require_liveness=body.options.require_liveness,
        idempotency_key=idempotency_key,
    )

    payload = _verification_response(result).model_dump(mode="json")
    if cache_key:
        await store_response(cache_key, payload)
    return payload


@router.get(
    "/verifications",
    response_model=Page[VerificationListItem],
    summary="List verification sessions",
)
async def list_verifications(
    principal: ReadVerifications,
    session: DbSession,
    decision: str | None = None,
    subject_id: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[VerificationListItem]:
    organization_id = principal.require_organization

    statement = (
        select(VerificationSession, Subject.external_id)
        .outerjoin(Subject, VerificationSession.subject_id == Subject.id)
        .where(VerificationSession.organization_id == organization_id)
    )
    if decision:
        statement = statement.where(VerificationSession.decision == decision)
    if subject_id:
        statement = statement.where(VerificationSession.subject_id == subject_id)
    if cursor:
        statement = statement.where(VerificationSession.id < decode_cursor(cursor))

    statement = statement.order_by(VerificationSession.id.desc()).limit(limit + 1)
    rows = (await session.execute(statement)).all()

    has_more = len(rows) > limit
    page = rows[:limit]

    return Page(
        data=[_list_item(row, external_id) for row, external_id in page],
        pagination=Pagination(
            next_cursor=encode_cursor(page[-1][0].id) if has_more and page else None,
            has_more=has_more,
            limit=limit,
        ),
    )


@router.get(
    "/verifications/{verification_id}",
    response_model=VerificationDetail,
    summary="Verification detail",
    description=(
        "Includes the threshold that was applied at the time. A later threshold change "
        "does not alter this record - an audit trail that moves is not an audit trail."
    ),
)
async def get_verification(
    verification_id: str,
    principal: ReadVerifications,
    session: DbSession,
) -> VerificationDetail:
    from app.core.exceptions import NotFoundError

    organization_id = principal.require_organization
    row = await session.get(VerificationSession, verification_id)
    if row is None or row.organization_id != organization_id:
        # Indistinguishable from missing. A 403 here would confirm existence
        # across the tenant boundary.
        raise NotFoundError(f"Verification '{verification_id}' was not found.")

    external_id: str | None = None
    if row.subject_id:
        subject = await session.get(Subject, row.subject_id)
        external_id = subject.external_id if subject else None

    report = row.quality_report or {}
    base = _list_item(row, external_id)
    return VerificationDetail(
        **base.model_dump(),
        templates_compared=row.templates_compared,
        detect_ms=row.detect_ms,
        embed_ms=row.embed_ms,
        match_ms=row.match_ms,
        ip_address=row.ip_address,
        user_agent=row.user_agent,
        quality=report.get("quality"),
        liveness=report.get("liveness"),
    )


# `/usage/current` is served by the analytics module, which already owns the
# rollup reads and is what the console calls. `VerificationService.quota_state`
# is the enforcement path; both read `usage_daily`, so the number a customer
# sees and the number that blocks them cannot disagree.


@router.get(
    "/threshold",
    response_model=ThresholdInfo,
    summary="The active threshold and its measured error rates",
    description=(
        "FAR and FRR come from the Phase 0 calibration run on 8,559 genuine and 500,000 "
        "impostor pairs. `measured` is false when the configuration has no calibrated "
        "figures - a custom threshold reports nothing rather than a reassuring zero."
    ),
)
async def threshold_info(
    principal: ReadVerifications,
    session: DbSession,
) -> ThresholdInfo:
    from app.core.exceptions import NotFoundError

    row = await session.get(OrgSettings, principal.require_organization)
    if row is None:
        raise NotFoundError("Organization settings not found.")
    return ThresholdInfo(**describe_threshold(row.match_threshold))


# ── Serialization ─────────────────────────────────────────────────────────────


def _verification_response(row: VerificationSession) -> VerificationResponse:
    report = row.quality_report or {}
    return VerificationResponse(
        id=row.id,
        decision=row.decision,
        subject_id=row.subject_id,
        similarity=float(row.similarity) if row.similarity is not None else None,
        threshold=float(row.threshold_applied),
        confidence=row.confidence,
        failure_reason=row.failure_reason,
        guidance=report.get("guidance"),
        templates_compared=row.templates_compared,
        quality=report.get("quality"),
        liveness=report.get("liveness"),
        timing={
            "total_ms": row.latency_ms,
            "detect_ms": row.detect_ms,
            "embed_ms": row.embed_ms,
            "match_ms": row.match_ms,
        },
        created_at=row.created_at,
    )


def _list_item(row: VerificationSession, external_id: str | None) -> VerificationListItem:
    return VerificationListItem(
        id=row.id,
        subject_id=row.subject_id,
        subject_external_id=external_id,
        decision=row.decision,
        similarity=float(row.similarity) if row.similarity is not None else None,
        threshold_applied=float(row.threshold_applied),
        confidence=row.confidence,
        failure_reason=row.failure_reason,
        latency_ms=row.latency_ms,
        source=row.source,
        created_at=row.created_at,
    )


def _seconds_until_next_month() -> int:
    """When the quota actually resets.

    A generic `Retry-After: 60` on an exhausted monthly quota is a lie that
    invites a client to hammer a limit that will not move for days.
    """
    from datetime import UTC, datetime

    now = datetime.now(tz=UTC)
    if now.month == 12:
        reset = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0)
    else:
        reset = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0)
    return max(1, int((reset - now.replace(microsecond=0)).total_seconds()))


@router.get(
    "/threshold/simulate",
    response_model=ThresholdSimulation,
    summary="Replay history against a candidate threshold",
    description=(
        "Answers what the threshold slider cannot: **what would this have done to my "
        "traffic?**\n\n"
        "Replays the `similarity` already stored on each past session against a "
        "candidate threshold. No inference runs and no new data is needed — the "
        "decisions were recorded with the threshold that produced them.\n\n"
        "`inconclusive` sessions are excluded: the pipeline stopped before matching, "
        "so no threshold would have changed them. Counting them would make the "
        "simulation look more decisive than it is.\n\n"
        "The published FAR/FRR figures come from a public benchmark that is easier "
        "than production ([model card](https://github.com/fvas/docs/16-model-card.md)). "
        "This gives you your own numbers instead."
    ),
)
async def simulate_threshold(
    principal: ReadVerifications,
    session: DbSession,
    threshold: Annotated[Decimal, Query(gt=0, lt=1, description="Candidate threshold")],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> ThresholdSimulation:
    from app.core.exceptions import NotFoundError
    from app.modules.analytics.simulator import ThresholdSimulator

    settings_row = await session.get(OrgSettings, principal.require_organization)
    if settings_row is None:
        raise NotFoundError("Organization settings not found.")

    simulator = ThresholdSimulator(session, principal.require_organization)
    result = await simulator.run(
        candidate=threshold,
        current=settings_row.match_threshold,
        days=days,
    )

    return ThresholdSimulation(
        current_threshold=result.current_threshold,
        candidate_threshold=result.candidate_threshold,
        window_days=result.window_days,
        comparable=result.comparable,
        unchanged=result.unchanged,
        original_verified=result.original_verified,
        original_rejected=result.original_rejected,
        simulated_verified=result.simulated_verified,
        simulated_rejected=result.simulated_rejected,
        newly_rejected=result.newly_rejected,
        newly_accepted=result.newly_accepted,
        acceptance_rate_before=round(result.acceptance_rate_before, 4),
        acceptance_rate_after=round(result.acceptance_rate_after, 4),
        examples=[
            SimulatedFlip(
                id=flip.id,
                subject_id=flip.subject_id,
                subject_external_id=flip.subject_external_id,
                similarity=flip.similarity,
                original_decision=flip.original_decision,
                simulated_decision=flip.simulated_decision,
                confidence=flip.confidence,
                created_at=flip.created_at,
            )
            for flip in result.examples
        ],
        histogram=[SimilarityBucket(**bucket) for bucket in result.histogram],
    )
