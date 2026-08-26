"""Retention enforcement.

A dry run that finds nothing proves nothing. These build data on both sides of
a cutoff and assert that exactly the right side disappears.

The property that matters most is the one that is easiest to get catastrophically
wrong: a retention job that deletes *more* than its window is a data-loss
incident, and it would look identical in the logs to one that worked.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.biometrics.models import AuditLog, UsageDaily, VerificationSession
from app.modules.identity.models import Organization, OrgSettings
from app.modules.platform.retention import enforce_retention


async def _organization(
    session: AsyncSession, identifier: str, *, retention_days: int
) -> Organization:
    organization = Organization(id=identifier, name=identifier, slug=identifier)
    session.add(organization)
    await session.flush()
    session.add(OrgSettings(organization_id=organization.id, log_retention_days=retention_days))
    await session.commit()
    return organization


def _session_row(organization_id: str, *, age_days: int) -> VerificationSession:
    moment = datetime.now(tz=UTC) - timedelta(days=age_days)
    return VerificationSession(
        organization_id=organization_id,
        decision="verified",
        threshold_applied="0.380",
        created_at=moment,
        updated_at=moment,
    )


async def test_rows_past_the_window_are_deleted_and_recent_ones_are_kept(
    session: AsyncSession,
) -> None:
    organization = await _organization(session, "org_keep30", retention_days=30)

    session.add_all(
        [
            _session_row(organization.id, age_days=1),
            _session_row(organization.id, age_days=29),
            _session_row(organization.id, age_days=31),
            _session_row(organization.id, age_days=400),
        ]
    )
    await session.commit()

    report = await enforce_retention(session)

    assert report.verification_sessions == 2
    remaining = await session.scalar(select(func.count()).select_from(VerificationSession))
    assert remaining == 2


async def test_each_organization_gets_its_own_window(session: AsyncSession) -> None:
    """Retention is a plan term. A Growth customer keeping 90 days must not be
    trimmed to a Free customer's 7.
    """
    short = await _organization(session, "org_free", retention_days=7)
    long = await _organization(session, "org_growth", retention_days=90)

    session.add_all(
        [
            _session_row(short.id, age_days=10),
            _session_row(long.id, age_days=10),
        ]
    )
    await session.commit()

    await enforce_retention(session)

    survivors = list(await session.scalars(select(VerificationSession.organization_id)))
    assert survivors == [long.id]


async def test_zero_means_keep_forever(session: AsyncSession) -> None:
    """The most destructive possible reading of an unset value would be
    "delete everything". It means the opposite.
    """
    organization = await _organization(session, "org_unlimited", retention_days=0)
    session.add(_session_row(organization.id, age_days=3650))
    await session.commit()

    report = await enforce_retention(session)

    assert report.verification_sessions == 0
    assert await session.scalar(select(func.count()).select_from(VerificationSession)) == 1


async def test_rollups_survive_so_historical_charts_do_not_collapse(
    session: AsyncSession,
) -> None:
    """Analytics reads `usage_daily`, never the raw table. Expiring the
    drill-down detail must not erase a customer's history.
    """
    organization = await _organization(session, "org_rollup", retention_days=7)
    old = datetime.now(tz=UTC) - timedelta(days=200)
    session.add(_session_row(organization.id, age_days=200))
    session.add(
        UsageDaily(
            organization_id=organization.id,
            day=old.strftime("%Y-%m-%d"),
            metric="verifications",
            count=500,
        )
    )
    await session.commit()

    await enforce_retention(session)

    assert await session.scalar(select(func.count()).select_from(VerificationSession)) == 0
    rollup = (await session.execute(select(UsageDaily))).scalar_one()
    assert rollup.count == 500


async def test_audit_entries_expire_with_the_same_window(session: AsyncSession) -> None:
    organization = await _organization(session, "org_audit", retention_days=7)
    old = datetime.now(tz=UTC) - timedelta(days=30)
    session.add(
        AuditLog(
            organization_id=organization.id,
            action="subject.created",
            resource_type="subject",
            created_at=old,
            updated_at=old,
        )
    )
    session.add(
        AuditLog(
            organization_id=organization.id,
            action="subject.created",
            resource_type="subject",
        )
    )
    await session.commit()

    report = await enforce_retention(session)

    assert report.audit_logs == 1
    assert await session.scalar(select(func.count()).select_from(AuditLog)) == 1


async def test_running_twice_deletes_nothing_the_second_time(session: AsyncSession) -> None:
    """Idempotent, so a nightly job that overlaps its predecessor is harmless."""
    organization = await _organization(session, "org_twice", retention_days=7)
    session.add(_session_row(organization.id, age_days=100))
    await session.commit()

    first = await enforce_retention(session)
    second = await enforce_retention(session)

    assert first.verification_sessions == 1
    assert second.verification_sessions == 0


async def test_an_organization_with_no_expired_data_is_untouched(
    session: AsyncSession,
) -> None:
    organization = await _organization(session, "org_fresh", retention_days=30)
    session.add(_session_row(organization.id, age_days=1))
    await session.commit()

    report = await enforce_retention(session)

    assert report.organizations == 1
    assert report.verification_sessions == 0
    assert report.per_organization == {}
