"""webhook endpoints and deliveries

Revision ID: 0006
Revises: 0005
Created: 2026-08-01

Delivery is at-least-once and persisted, not fire-and-forget. Two reasons:

  * "did you send it?" is the first question in every webhook support thread,
    and an answer of "probably" is worthless;
  * retries have to survive a process restart, which an in-memory queue does
    not. A row with `next_retry_at` is the whole scheduler.

`ix_webhook_deliveries_due` is partial on `status = 'pending'`. Delivered rows
are the overwhelming majority and the worker never looks at them, so keeping
them out of the index keeps it small enough to stay cached as the table grows.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.types.TypeEngine[object]:
    """JSONB on PostgreSQL, JSON elsewhere — matching the model's variant."""
    return sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(40),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("events", _json(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("secret", sa.String(128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_webhook_endpoints_org", "webhook_endpoints", ["organization_id", "is_active"]
    )
    op.create_index("ix_webhook_endpoints_deleted_at", "webhook_endpoints", ["deleted_at"])

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(40),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "endpoint_id",
            sa.String(40),
            sa.ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("event_id", sa.String(40), nullable=False),
        sa.Column("payload", _json(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.String(1000), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'delivered', 'failed')",
            name="ck_webhook_deliveries_status",
        ),
    )
    op.create_index(
        "ix_webhook_deliveries_org_created",
        "webhook_deliveries",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_webhook_deliveries_endpoint", "webhook_deliveries", ["endpoint_id", "created_at"]
    )
    op.create_index(
        "ix_webhook_deliveries_due",
        "webhook_deliveries",
        ["next_retry_at"],
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_endpoints")
