"""identity and auth schema

Revision ID: 0002
Revises: 0001
Created: 2026-07-31

Organizations, users, the RBAC tables, memberships, invitations, and the token
and auth-log tables that authentication needs.

Enum-like columns are VARCHAR + CHECK rather than native Postgres ENUMs: adding
a value to a native enum requires ALTER TYPE, which complicates rollback for no
benefit here.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("plan", sa.String(20), nullable=False, server_default="free"),
        sa.Column("region", sa.String(32), nullable=False, server_default="ap-southeast"),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("billing_email", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "plan IN ('free', 'startup', 'growth', 'enterprise')",
            name="ck_organizations_plan",
        ),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])
    op.create_index("ix_organizations_deleted_at", "organizations", ["deleted_at"])

    op.create_table(
        "org_settings",
        sa.Column(
            "organization_id",
            sa.String(40),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("match_threshold", sa.Numeric(4, 3), nullable=False, server_default="0.380"),
        sa.Column("threshold_preset", sa.String(20), nullable=False, server_default="balanced"),
        sa.Column("duplicate_check_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("duplicate_threshold", sa.Numeric(4, 3), nullable=False, server_default="0.600"),
        sa.Column("min_face_size_px", sa.Integer(), nullable=False, server_default="112"),
        sa.Column("require_liveness", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("max_templates_per_profile", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("store_raw_images", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("image_retention_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("log_retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("ip_allowlist", sa.Text(), nullable=True),
        sa.Column("webhook_signing_secret", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "threshold_preset IN ('lenient', 'balanced', 'strict', 'custom')",
            name="ck_org_settings_preset",
        ),
        sa.CheckConstraint(
            "match_threshold > 0 AND match_threshold < 1",
            name="ck_org_settings_match_threshold_range",
        ),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(120), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])

    op.create_table(
        "permissions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("resource", sa.String(32), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "roles",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(40),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("slug", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "slug", name="uq_roles_org_slug"),
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.String(40), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "permission_id",
            sa.String(40),
            sa.ForeignKey("permissions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "memberships",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(40),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.String(40), sa.ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_memberships_org_user"),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_memberships_status"),
    )
    op.create_index("ix_memberships_user", "memberships", ["user_id"])
    op.create_index("ix_memberships_org", "memberships", ["organization_id", "status"])

    op.create_table(
        "invitations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(40),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role_id", sa.String(40), sa.ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "invited_by_user_id",
            sa.String(40),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')",
            name="ck_invitations_status",
        ),
    )
    op.create_index("ix_invitations_token", "invitations", ["token_hash"])
    # Partial: one *live* invite per email per org. A full unique index would
    # permanently block re-inviting someone whose invite was revoked.
    op.create_index(
        "uq_invitations_pending",
        "invitations",
        ["organization_id", "email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("family_id", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.String(40), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_refresh_tokens_hash", "refresh_tokens", ["token_hash"])
    op.create_index("ix_refresh_tokens_family", "refresh_tokens", ["family_id"])
    op.create_index("ix_refresh_tokens_user", "refresh_tokens", ["user_id"])

    for table in ("password_reset_tokens", "email_verification_tokens"):
        op.create_table(
            table,
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index(f"ix_{table}_hash", table, ["token_hash"])

    op.create_table(
        "auth_logs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("event", sa.String(48), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_auth_logs_user", "auth_logs", ["user_id", "created_at"])
    op.create_index("ix_auth_logs_event", "auth_logs", ["event", "created_at"])
    op.create_index("ix_auth_logs_email", "auth_logs", ["email"])


def downgrade() -> None:
    # Reverse creation order so foreign keys never block a drop.
    for table in (
        "auth_logs",
        "email_verification_tokens",
        "password_reset_tokens",
        "refresh_tokens",
        "invitations",
        "memberships",
        "role_permissions",
        "roles",
        "permissions",
        "users",
        "org_settings",
        "organizations",
    ):
        op.drop_table(table)
