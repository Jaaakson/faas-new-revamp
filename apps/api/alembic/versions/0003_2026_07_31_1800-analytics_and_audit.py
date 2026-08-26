"""subjects, verification sessions, usage rollups, audit log

Revision ID: 0003
Revises: 0002
Created: 2026-07-31

The schema analytics and the console read from. Biometric behaviour lands in
Phases 5-6; the face_profiles / face_templates tables are deliberately deferred
until something can write to them, so their deletion guarantees ship tested.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# Matches app.modules.biometrics.models.JsonColumn.
JSON_COLUMN = sa.JSON().with_variant(JSONB(), "postgresql")

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "subjects",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(40),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=True),
        sa.Column("metadata", JSON_COLUMN, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("consent_reference", sa.String(128), nullable=True),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('pending', 'enrolled', 'suspended')", name="ck_subjects_status"
        ),
    )
    op.create_index(
        "uq_subjects_org_external", "subjects", ["organization_id", "external_id"], unique=True
    )
    op.create_index(
        "ix_subjects_org_status", "subjects", ["organization_id", "status", "created_at"]
    )
    op.create_index("ix_subjects_deleted_at", "subjects", ["deleted_at"])

    op.create_table(
        "verification_sessions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(40),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subject_id", sa.String(40), sa.ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("similarity", sa.Numeric(6, 5), nullable=True),
        sa.Column("threshold_applied", sa.Numeric(4, 3), nullable=False),
        sa.Column("confidence", sa.String(10), nullable=True),
        sa.Column("failure_reason", sa.String(32), nullable=True),
        sa.Column("templates_compared", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quality_report", JSON_COLUMN, nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detect_ms", sa.Integer(), nullable=True),
        sa.Column("embed_ms", sa.Integer(), nullable=True),
        sa.Column("match_ms", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="api"),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "decision IN ('verified', 'rejected', 'inconclusive', 'error')",
            name="ck_verification_sessions_decision",
        ),
    )
    op.create_index(
        "ix_verifications_org_created", "verification_sessions", ["organization_id", "created_at"]
    )
    op.create_index(
        "ix_verifications_org_decision",
        "verification_sessions",
        ["organization_id", "decision", "created_at"],
    )
    op.create_index(
        "ix_verifications_org_subject",
        "verification_sessions",
        ["organization_id", "subject_id", "created_at"],
    )
    op.create_index(
        "uq_verifications_idempotency",
        "verification_sessions",
        ["organization_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "usage_daily",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(40),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("metric", sa.String(24), nullable=False),
        sa.Column("count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("inconclusive_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("p95_latency_ms", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
    )
    op.create_index(
        "uq_usage_daily", "usage_daily", ["organization_id", "day", "metric"], unique=True
    )
    op.create_index("ix_usage_daily_org_day", "usage_daily", ["organization_id", "day"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(40),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_type", sa.String(16), nullable=False, server_default="user"),
        sa.Column("actor_id", sa.String(40), nullable=True),
        sa.Column("actor_email", sa.String(255), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(40), nullable=True),
        sa.Column("changes", JSON_COLUMN, nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("request_id", sa.String(48), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "actor_type IN ('user', 'api_key', 'system')", name="ck_audit_logs_actor_type"
        ),
    )
    op.create_index("ix_audit_logs_org_created", "audit_logs", ["organization_id", "created_at"])
    op.create_index(
        "ix_audit_logs_org_action", "audit_logs", ["organization_id", "action", "created_at"]
    )
    op.create_index(
        "ix_audit_logs_resource", "audit_logs", ["organization_id", "resource_type", "resource_id"]
    )


def downgrade() -> None:
    for table in ("audit_logs", "usage_daily", "verification_sessions", "subjects"):
        op.drop_table(table)
