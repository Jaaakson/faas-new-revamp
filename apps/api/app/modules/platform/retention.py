"""Retention enforcement.

Every plan carries a log-retention window, and a promise to delete past it is
worth nothing unless something actually deletes. This is that something — run
nightly (`python -m app.cli retention`).

Three properties matter more than the deletion itself:

* **Per-tenant windows.** Retention is a plan term, so the cutoff is computed
  per organization from `org_settings.log_retention_days`, not globally. A
  Growth customer keeping 90 days must not have their data trimmed to a Free
  customer's 7.

* **Batched deletes.** A single `DELETE` over a year of the highest-volume table
  in the system takes a long lock and bloats the table with dead tuples. Small
  batches keep each transaction short and let autovacuum keep up.

* **Rollups survive.** `usage_daily` is what analytics reads; deleting raw
  sessions must not make a customer's historical charts collapse. Only the
  drill-down detail expires.

Deletion is logged, per the plan's own commitment
(docs/06-database.md §6) — an unlogged retention job cannot be shown to have run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.biometrics.models import AuditLog, VerificationSession, WebhookDelivery
from app.modules.identity.models import Organization, OrgSettings
from app.shared.base_model import IDMixin

logger = structlog.get_logger(__name__)

# Rows per statement. Small enough that each transaction is short, large enough
# that a year of backlog does not take all night.
BATCH_SIZE = 5_000

# Deliveries are operational exhaust, not customer records, and they are the
# fastest-growing table per event. A fixed window is right here regardless of
# plan.
WEBHOOK_DELIVERY_RETENTION_DAYS = 30


@dataclass
class RetentionReport:
    organizations: int = 0
    verification_sessions: int = 0
    audit_logs: int = 0
    webhook_deliveries: int = 0
    per_organization: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "organizations": self.organizations,
            "verification_sessions_deleted": self.verification_sessions,
            "audit_logs_deleted": self.audit_logs,
            "webhook_deliveries_deleted": self.webhook_deliveries,
        }


async def _delete_in_batches(
    session: AsyncSession,
    model: type[IDMixin],
    *conditions: ColumnElement[bool],
) -> int:
    """Delete matching rows a batch at a time. Returns the total removed."""
    total = 0
    while True:
        # Select the ids first, then delete by primary key. `DELETE ... LIMIT`
        # is not portable, and deleting by an indexed PK list keeps each
        # statement's plan predictable.
        ids = list(await session.scalars(select(model.id).where(*conditions).limit(BATCH_SIZE)))
        if not ids:
            return total

        result = await session.execute(delete(model).where(model.id.in_(ids)))
        removed = int(result.rowcount or 0)  # type: ignore[attr-defined]
        await session.commit()

        total += removed
        if removed < BATCH_SIZE:
            return total


async def enforce_retention(
    session: AsyncSession, *, now: datetime | None = None
) -> RetentionReport:
    """Apply every organization's retention window. Idempotent."""
    moment = now or datetime.now(tz=UTC)
    report = RetentionReport()

    rows = list(
        await session.execute(
            select(Organization.id, OrgSettings.log_retention_days).join(
                OrgSettings, OrgSettings.organization_id == Organization.id
            )
        )
    )

    for organization_id, retention_days in rows:
        report.organizations += 1
        if not retention_days or retention_days <= 0:
            # Zero means "keep indefinitely". Treating it as "delete everything"
            # would be the most destructive possible reading of an unset value.
            continue

        cutoff = moment - timedelta(days=int(retention_days))

        sessions_removed = await _delete_in_batches(
            session,
            VerificationSession,
            VerificationSession.organization_id == organization_id,
            VerificationSession.created_at < cutoff,
        )
        audit_removed = await _delete_in_batches(
            session,
            AuditLog,
            AuditLog.organization_id == organization_id,
            AuditLog.created_at < cutoff,
        )

        report.verification_sessions += sessions_removed
        report.audit_logs += audit_removed
        if sessions_removed or audit_removed:
            report.per_organization[organization_id] = sessions_removed + audit_removed
            logger.info(
                "retention_applied",
                organization_id=organization_id,
                retention_days=int(retention_days),
                cutoff=cutoff.isoformat(),
                verification_sessions=sessions_removed,
                audit_logs=audit_removed,
            )

    report.webhook_deliveries = await _delete_in_batches(
        session,
        WebhookDelivery,
        WebhookDelivery.created_at < moment - timedelta(days=WEBHOOK_DELIVERY_RETENTION_DAYS),
        WebhookDelivery.status != "pending",
    )

    logger.info("retention_complete", **report.as_dict())
    return report
