"""Analytics aggregation and tenant scoping.

The numbers on the console's front page come from here. A silently wrong
success rate is worse than a broken chart — it looks authoritative.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.service import AnalyticsService, _change_pct
from app.modules.biometrics.models import Subject, VerificationSession
from app.modules.identity.models import Organization, OrgSettings


async def _make_org(session: AsyncSession, slug: str) -> Organization:
    organization = Organization(name=slug.title(), slug=slug, plan="growth")
    session.add(organization)
    await session.flush()
    session.add(OrgSettings(organization_id=organization.id))
    await session.flush()
    return organization


async def _make_subject(session: AsyncSession, org_id: str, external_id: str) -> Subject:
    subject = Subject(organization_id=org_id, external_id=external_id, status="enrolled")
    session.add(subject)
    await session.flush()
    return subject


def _session_row(
    org_id: str,
    subject_id: str,
    *,
    decision: str,
    latency: int = 250,
    created_at: datetime | None = None,
    similarity: str | None = "0.8",
) -> VerificationSession:
    return VerificationSession(
        organization_id=org_id,
        subject_id=subject_id,
        decision=decision,
        similarity=Decimal(similarity) if similarity else None,
        threshold_applied=Decimal("0.380"),
        latency_ms=latency,
        created_at=created_at or datetime.now(tz=UTC),
    )


# ── Change percentage ─────────────────────────────────────────────────────────


def test_change_pct_returns_none_without_a_baseline() -> None:
    """No prior data must not render as '+0%'.

    Zero implies "measured, unchanged". None lets the UI say "no prior period",
    which is the truth.
    """
    assert _change_pct(100, 0) is None


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [(110, 100, 10.0), (90, 100, -10.0), (100, 100, 0.0), (0, 50, -100.0)],
)
def test_change_pct(current: float, previous: float, expected: float) -> None:
    assert _change_pct(current, previous) == expected


# ── Success rate ──────────────────────────────────────────────────────────────


async def test_success_rate_excludes_errors_from_the_denominator(
    session: AsyncSession,
) -> None:
    """Our pipeline failing is not the customer's verification failing.

    Counting `error` against the customer would make our own incident show up
    as their success rate dropping — and they would go looking for fraud.
    """
    org = await _make_org(session, "acme")
    subject = await _make_subject(session, org.id, "user_1")

    for _ in range(8):
        session.add(_session_row(org.id, subject.id, decision="verified"))
    for _ in range(2):
        session.add(_session_row(org.id, subject.id, decision="rejected"))
    for _ in range(10):
        session.add(_session_row(org.id, subject.id, decision="error"))
    await session.commit()

    overview = await AnalyticsService(session).overview(org.id, days=7)

    # 8 verified of 10 decidable = 80%, not 8 of 20 = 40%.
    assert overview.success_rate.value == pytest.approx(80.0)
    assert overview.verifications.value == 20


async def test_success_rate_is_zero_when_nothing_was_decidable(
    session: AsyncSession,
) -> None:
    org = await _make_org(session, "acme")
    subject = await _make_subject(session, org.id, "user_1")
    session.add(_session_row(org.id, subject.id, decision="error"))
    await session.commit()

    overview = await AnalyticsService(session).overview(org.id, days=7)

    assert overview.success_rate.value == 0.0
    assert overview.has_any_data is True


async def test_has_any_data_distinguishes_empty_from_filtered(
    session: AsyncSession,
) -> None:
    """A brand-new tenant needs onboarding; a quiet week needs a date hint."""
    org = await _make_org(session, "acme")
    subject = await _make_subject(session, org.id, "user_1")

    empty = await AnalyticsService(session).overview(org.id, days=7)
    assert empty.has_any_data is False

    # Older than the 7-day window, so the window is empty but the tenant is not.
    session.add(
        _session_row(
            org.id,
            subject.id,
            decision="verified",
            created_at=datetime.now(tz=UTC) - timedelta(days=40),
        )
    )
    await session.commit()

    stale = await AnalyticsService(session).overview(org.id, days=7)
    assert stale.verifications.value == 0
    assert stale.has_any_data is True


# ── Tenant isolation ──────────────────────────────────────────────────────────


async def test_analytics_never_cross_the_tenant_boundary(session: AsyncSession) -> None:
    acme = await _make_org(session, "acme")
    globex = await _make_org(session, "globex")
    acme_subject = await _make_subject(session, acme.id, "user_1")
    globex_subject = await _make_subject(session, globex.id, "user_1")

    for _ in range(5):
        session.add(_session_row(acme.id, acme_subject.id, decision="verified"))
    for _ in range(50):
        session.add(_session_row(globex.id, globex_subject.id, decision="rejected"))
    await session.commit()

    service = AnalyticsService(session)
    acme_overview = await service.overview(acme.id, days=7)
    outcomes = await service.outcomes(acme.id, days=30)

    assert acme_overview.verifications.value == 5
    assert acme_overview.success_rate.value == pytest.approx(100.0)
    assert {slice_.decision for slice_ in outcomes} == {"verified"}


# ── Percentiles ───────────────────────────────────────────────────────────────


async def test_latency_percentiles_reflect_the_tail(session: AsyncSession) -> None:
    """p99 must not collapse onto p95 when a real tail exists."""
    org = await _make_org(session, "acme")
    subject = await _make_subject(session, org.id, "user_1")

    for _ in range(95):
        session.add(_session_row(org.id, subject.id, decision="verified", latency=200))
    for _ in range(4):
        session.add(_session_row(org.id, subject.id, decision="verified", latency=600))
    session.add(_session_row(org.id, subject.id, decision="verified", latency=3000))
    await session.commit()

    distribution = await AnalyticsService(session).latency_distribution(org.id, days=30)

    assert distribution.p50 == 200
    assert distribution.p95 >= 200
    assert distribution.p99 > distribution.p95

    buckets = {bucket.bucket: bucket.count for bucket in distribution.buckets}
    assert buckets["200-300"] == 95
    assert buckets[">1s"] == 1


# ── Rollups ───────────────────────────────────────────────────────────────────


async def test_rollups_are_idempotent(session: AsyncSession) -> None:
    """The nightly job must be safe to re-run after a backfill."""
    org = await _make_org(session, "acme")
    subject = await _make_subject(session, org.id, "user_1")
    for _ in range(6):
        session.add(_session_row(org.id, subject.id, decision="verified"))
    await session.commit()

    service = AnalyticsService(session)
    await service.rebuild_rollups(org.id, days=90)
    first = await service.timeseries(org.id, days=7)

    await service.rebuild_rollups(org.id, days=90)
    second = await service.timeseries(org.id, days=7)

    assert [point.total for point in first] == [point.total for point in second]
    assert sum(point.total for point in second) == 6


async def test_timeseries_fills_quiet_days_with_zero(session: AsyncSession) -> None:
    """A line chart that skips quiet days misrepresents the trend."""
    org = await _make_org(session, "acme")
    subject = await _make_subject(session, org.id, "user_1")
    session.add(_session_row(org.id, subject.id, decision="verified"))
    await session.commit()

    service = AnalyticsService(session)
    await service.rebuild_rollups(org.id, days=90)
    points = await service.timeseries(org.id, days=14)

    assert len(points) == 14
    assert sum(point.total for point in points) == 1
    # Every day present, in ascending order, with no gaps.
    assert [point.day for point in points] == sorted(point.day for point in points)


# ── Usage ─────────────────────────────────────────────────────────────────────


async def test_usage_does_not_bill_pipeline_errors(session: AsyncSession) -> None:
    org = await _make_org(session, "acme")
    subject = await _make_subject(session, org.id, "user_1")
    for _ in range(4):
        session.add(_session_row(org.id, subject.id, decision="verified"))
    for _ in range(3):
        session.add(_session_row(org.id, subject.id, decision="error"))
    await session.commit()

    usage = await AnalyticsService(session).usage(org.id, plan="growth")

    assert usage.used == 4
    assert usage.limit == 150_000


async def test_enterprise_usage_has_no_limit(session: AsyncSession) -> None:
    org = await _make_org(session, "acme")
    usage = await AnalyticsService(session).usage(org.id, plan="enterprise")

    assert usage.limit is None
    assert usage.percentage == 0.0


# ── Heatmap ───────────────────────────────────────────────────────────────────


async def test_hourly_heatmap_covers_every_cell(session: AsyncSession) -> None:
    """168 cells always, so the grid never renders ragged."""
    org = await _make_org(session, "acme")
    subject = await _make_subject(session, org.id, "user_1")
    session.add(_session_row(org.id, subject.id, decision="verified"))
    await session.commit()

    cells = await AnalyticsService(session).hourly_heatmap(org.id, days=30)

    assert len(cells) == 7 * 24
    # Cells with no traffic report None, not 0% — which would read as total failure.
    assert all(cell.success_rate is None for cell in cells if cell.total == 0)
