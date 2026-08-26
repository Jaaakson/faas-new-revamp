"""Analytics aggregation.

Reads pre-aggregated `usage_daily` rows wherever a chart spans days, and drops
to `verification_sessions` only for drill-down and distributions. That split is
what keeps the dashboard fast at 10M rows instead of timing out at 500K
(docs/06-database.md §6).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import get_plan
from app.modules.analytics.schemas import (
    FailureReason,
    HourlyCell,
    LatencyBucket,
    LatencyDistribution,
    MetricDelta,
    OutcomeSlice,
    OverviewResponse,
    TimeseriesPoint,
    UsageResponse,
)
from app.modules.biometrics.models import UsageDaily, VerificationSession

LATENCY_BUCKETS: list[tuple[str, int, int]] = [
    ("<100ms", 0, 100),
    ("100-200", 100, 200),
    ("200-300", 200, 300),
    ("300-500", 300, 500),
    ("500ms-1s", 500, 1000),
    (">1s", 1000, 10**9),
]


def _change_pct(current: float, previous: float) -> float | None:
    """Percentage change, or None when there is no baseline.

    Returning None rather than 0 or infinity matters: the UI must be able to
    show "no prior data" instead of a meaningless "+0%" or "+∞%".
    """
    if previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 1)


def _window(organization_id: str, start: datetime, end: datetime | None) -> list[Any]:
    """Filter clauses for a time window.

    Half-open (`>= start`, `< end`) between adjacent windows so a row on the
    boundary is never counted twice. `end=None` means the current window, which
    has no upper bound at all — bounding it by `now` drops any verification
    written in the same clock tick as the request, and on a coarse-resolution
    clock that is not hypothetical.
    """
    clauses: list[Any] = [
        VerificationSession.organization_id == organization_id,
        VerificationSession.created_at >= start,
    ]
    if end is not None:
        clauses.append(VerificationSession.created_at < end)
    return clauses


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _scoped(self, organization_id: str) -> Select[tuple[VerificationSession]]:
        """Every query starts here. Nothing reads sessions unscoped."""
        return select(VerificationSession).where(
            VerificationSession.organization_id == organization_id
        )

    # ── Overview ──────────────────────────────────────────────────────────────

    async def overview(self, organization_id: str, days: int = 7) -> OverviewResponse:
        now = datetime.now(tz=UTC)
        current_start = now - timedelta(days=days)
        previous_start = now - timedelta(days=days * 2)

        current = await self._window_stats(organization_id, current_start, None)
        previous = await self._window_stats(organization_id, previous_start, current_start)

        total_ever = await self.session.scalar(
            select(func.count())
            .select_from(VerificationSession)
            .where(VerificationSession.organization_id == organization_id)
        )

        active_now = await self._active_subjects(organization_id, current_start, None)
        active_before = await self._active_subjects(organization_id, previous_start, current_start)

        return OverviewResponse(
            verifications=MetricDelta(
                value=current["total"],
                previous=previous["total"],
                change_pct=_change_pct(current["total"], previous["total"]),
                higher_is_better=True,
            ),
            success_rate=MetricDelta(
                value=current["success_rate"],
                previous=previous["success_rate"],
                change_pct=_change_pct(current["success_rate"], previous["success_rate"]),
                higher_is_better=True,
            ),
            p95_latency_ms=MetricDelta(
                value=current["p95"],
                previous=previous["p95"],
                change_pct=_change_pct(current["p95"], previous["p95"]),
                # The one metric where down is good.
                higher_is_better=False,
            ),
            active_subjects=MetricDelta(
                value=active_now,
                previous=active_before,
                change_pct=_change_pct(active_now, active_before),
                higher_is_better=True,
            ),
            period_days=days,
            has_any_data=bool(total_ever),
        )

    async def _window_stats(
        self, organization_id: str, start: datetime, end: datetime | None
    ) -> dict[str, float]:
        rows = list(
            await self.session.execute(
                select(VerificationSession.decision, func.count())
                .where(*_window(organization_id, start, end))
                .group_by(VerificationSession.decision)
            )
        )
        # Unpacked explicitly rather than `dict(rows)`: SQLAlchemy `Row` objects
        # are tuple-like at runtime but mypy will not accept them as pairs.
        counts: dict[str, int] = {}
        for decision, count in rows:
            counts[decision] = count

        total = sum(counts.values())
        verified = counts.get("verified", 0)

        # Errors are our fault, not a customer outcome, so they are excluded
        # from the denominator — otherwise our own incident would show up as
        # the customer's verification success rate dropping.
        decidable = total - counts.get("error", 0)
        success_rate = round((verified / decidable) * 100, 2) if decidable else 0.0

        return {
            "total": total,
            "success_rate": success_rate,
            "p95": await self._p95_latency(organization_id, start, end),
        }

    async def _p95_latency(
        self, organization_id: str, start: datetime, end: datetime | None
    ) -> float:
        """p95 by offset, not by percentile function.

        `percentile_cont` is Postgres-only; ordering and offsetting works on
        both backends and is exact for the row counts a single tenant produces.
        """
        total = (
            await self.session.scalar(
                select(func.count())
                .select_from(VerificationSession)
                .where(*_window(organization_id, start, end))
            )
            or 0
        )
        if total == 0:
            return 0.0

        offset = max(0, int(total * 0.95) - 1)
        value = await self.session.scalar(
            select(VerificationSession.latency_ms)
            .where(*_window(organization_id, start, end))
            .order_by(VerificationSession.latency_ms.asc())
            .offset(offset)
            .limit(1)
        )
        return float(value or 0)

    async def _active_subjects(
        self, organization_id: str, start: datetime, end: datetime | None
    ) -> int:
        return int(
            await self.session.scalar(
                select(func.count(func.distinct(VerificationSession.subject_id))).where(
                    VerificationSession.subject_id.is_not(None),
                    *_window(organization_id, start, end),
                )
            )
            or 0
        )

    # ── Charts ────────────────────────────────────────────────────────────────

    async def timeseries(self, organization_id: str, days: int = 30) -> list[TimeseriesPoint]:
        """Daily volume, read from the rollup table."""
        start_day = (datetime.now(tz=UTC).date() - timedelta(days=days - 1)).isoformat()

        rows = list(
            await self.session.scalars(
                select(UsageDaily)
                .where(
                    UsageDaily.organization_id == organization_id,
                    UsageDaily.metric == "verification",
                    UsageDaily.day >= start_day,
                )
                .order_by(UsageDaily.day.asc())
            )
        )
        by_day = {row.day: row for row in rows}

        # Fill gaps. A missing day is zero, not absent — a line chart that skips
        # quiet days silently misrepresents the trend.
        today = datetime.now(tz=UTC).date()
        points: list[TimeseriesPoint] = []
        for offset in range(days):
            day = (today - timedelta(days=days - 1 - offset)).isoformat()
            row = by_day.get(day)
            points.append(
                TimeseriesPoint(
                    day=day,
                    verified=row.success_count if row else 0,
                    rejected=row.rejected_count if row else 0,
                    inconclusive=row.inconclusive_count if row else 0,
                    total=row.count if row else 0,
                )
            )
        return points

    async def outcomes(self, organization_id: str, days: int = 30) -> list[OutcomeSlice]:
        start = datetime.now(tz=UTC) - timedelta(days=days)
        rows = list(
            await self.session.execute(
                select(VerificationSession.decision, func.count())
                .where(
                    VerificationSession.organization_id == organization_id,
                    VerificationSession.created_at >= start,
                )
                .group_by(VerificationSession.decision)
                .order_by(func.count().desc())
            )
        )
        total = sum(count for _, count in rows) or 1
        return [
            OutcomeSlice(
                decision=decision,
                count=count,
                percentage=round((count / total) * 100, 1),
            )
            for decision, count in rows
        ]

    async def failure_reasons(self, organization_id: str, days: int = 30) -> list[FailureReason]:
        start = datetime.now(tz=UTC) - timedelta(days=days)
        rows = list(
            await self.session.execute(
                select(VerificationSession.failure_reason, func.count())
                .where(
                    VerificationSession.organization_id == organization_id,
                    VerificationSession.failure_reason.is_not(None),
                    VerificationSession.created_at >= start,
                )
                .group_by(VerificationSession.failure_reason)
                .order_by(func.count().desc())
            )
        )
        total = sum(count for _, count in rows) or 1
        return [
            FailureReason(
                reason=reason or "unknown",
                count=count,
                percentage=round((count / total) * 100, 1),
            )
            for reason, count in rows
        ]

    async def latency_distribution(
        self, organization_id: str, days: int = 30
    ) -> LatencyDistribution:
        start = datetime.now(tz=UTC) - timedelta(days=days)
        latencies = list(
            await self.session.scalars(
                select(VerificationSession.latency_ms)
                .where(
                    VerificationSession.organization_id == organization_id,
                    VerificationSession.created_at >= start,
                )
                .order_by(VerificationSession.latency_ms.asc())
            )
        )

        buckets = [
            LatencyBucket(
                bucket=label,
                count=sum(1 for value in latencies if low <= value < high),
            )
            for label, low, high in LATENCY_BUCKETS
        ]

        def percentile(fraction: float) -> int:
            if not latencies:
                return 0
            return int(latencies[min(len(latencies) - 1, int(len(latencies) * fraction))])

        return LatencyDistribution(
            buckets=buckets,
            p50=percentile(0.50),
            p95=percentile(0.95),
            p99=percentile(0.99),
        )

    async def hourly_heatmap(self, organization_id: str, days: int = 30) -> list[HourlyCell]:
        """Success rate by weekday and hour.

        The one chart that produces an insight nobody asked for: a night-shift
        dip is almost always a lighting problem, not fraud. Computed in Python
        because date-part extraction differs across backends and the row count
        for one tenant over 30 days is small.
        """
        start = datetime.now(tz=UTC) - timedelta(days=days)
        rows = list(
            await self.session.execute(
                select(VerificationSession.created_at, VerificationSession.decision).where(
                    VerificationSession.organization_id == organization_id,
                    VerificationSession.created_at >= start,
                )
            )
        )

        grid: dict[tuple[int, int], list[int]] = {}
        for created_at, decision in rows:
            key = (created_at.weekday(), created_at.hour)
            grid.setdefault(key, []).append(1 if decision == "verified" else 0)

        cells: list[HourlyCell] = []
        for weekday in range(7):
            for hour in range(24):
                values = grid.get((weekday, hour), [])
                cells.append(
                    HourlyCell(
                        weekday=weekday,
                        hour=hour,
                        total=len(values),
                        success_rate=(
                            round((sum(values) / len(values)) * 100, 1) if values else None
                        ),
                    )
                )
        return cells

    # ── Usage ─────────────────────────────────────────────────────────────────

    async def usage(self, organization_id: str, plan: str) -> UsageResponse:
        today = datetime.now(tz=UTC).date()
        period_start = today.replace(day=1)
        next_month = (period_start + timedelta(days=32)).replace(day=1)
        period_end = next_month - timedelta(days=1)

        used = int(
            await self.session.scalar(
                select(func.count())
                .select_from(VerificationSession)
                .where(
                    VerificationSession.organization_id == organization_id,
                    VerificationSession.created_at
                    >= datetime.combine(period_start, datetime.min.time(), tzinfo=UTC),
                    # Errors are ours, so they are never billed.
                    VerificationSession.decision != "error",
                )
            )
            or 0
        )

        limits = get_plan(plan)
        limit = limits.monthly_verifications
        return UsageResponse(
            plan=plan,
            used=used,
            limit=limit,
            percentage=round((used / limit) * 100, 1) if limit else 0.0,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            days_remaining=(period_end - today).days,
            remaining=None if limit is None else max(0, limit - used),
            hard_stop=limits.hard_stop_at_quota,
        )

    # ── Rollup ────────────────────────────────────────────────────────────────

    async def rebuild_rollups(self, organization_id: str, days: int = 90) -> int:
        """Recompute `usage_daily` from raw sessions.

        Idempotent, so it can be re-run after a backfill or a bug without
        double-counting. In production this runs nightly; the seed calls it
        directly.
        """
        start = datetime.now(tz=UTC) - timedelta(days=days)

        rows = list(
            await self.session.execute(
                select(
                    VerificationSession.created_at,
                    VerificationSession.decision,
                    VerificationSession.latency_ms,
                ).where(
                    VerificationSession.organization_id == organization_id,
                    VerificationSession.created_at >= start,
                )
            )
        )

        buckets: dict[str, dict[str, list[int] | int]] = {}
        for created_at, decision, latency in rows:
            day = created_at.date().isoformat()
            bucket = buckets.setdefault(
                day,
                {"count": 0, "verified": 0, "rejected": 0, "inconclusive": 0, "latencies": []},
            )
            bucket["count"] = int(bucket["count"]) + 1  # type: ignore[arg-type]
            if decision in {"verified", "rejected", "inconclusive"}:
                bucket[decision] = int(bucket[decision]) + 1  # type: ignore[arg-type]
            latencies = bucket["latencies"]
            assert isinstance(latencies, list)  # noqa: S101
            latencies.append(latency)

        existing = {
            row.day: row
            for row in await self.session.scalars(
                select(UsageDaily).where(
                    UsageDaily.organization_id == organization_id,
                    UsageDaily.metric == "verification",
                )
            )
        }

        for day, bucket in buckets.items():
            latencies = sorted(bucket["latencies"])  # type: ignore[arg-type]
            p95 = (
                int(latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))])
                if latencies
                else 0
            )
            row = existing.get(day)
            if row is None:
                row = UsageDaily(organization_id=organization_id, day=day, metric="verification")
                self.session.add(row)
            row.count = int(bucket["count"])  # type: ignore[arg-type]
            row.success_count = int(bucket["verified"])  # type: ignore[arg-type]
            row.rejected_count = int(bucket["rejected"])  # type: ignore[arg-type]
            row.inconclusive_count = int(bucket["inconclusive"])  # type: ignore[arg-type]
            row.p95_latency_ms = p95

        await self.session.commit()
        return len(buckets)


def parse_day(value: str) -> date:
    return datetime.fromisoformat(value).date()
