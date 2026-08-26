"""api keys

Revision ID: 0007
Revises: 0006
Created: 2026-08-01

The credential for the public `/v1` API.

`key_prefix` is unique and indexed because it is the *lookup* key: authentication
parses the prefix from the presented secret, hits this index once, and then does
a single constant-time digest comparison. Without it, verifying a key would mean
hashing the candidate against every row in the table — a scan on the hottest path
in the product.

No `deleted_at`. Revocation is a timestamp, not a soft delete: a revoked key has
to stay visible so a customer can see what was revoked and when.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(40),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("environment", sa.String(8), nullable=False),
        sa.Column("key_prefix", sa.String(24), nullable=False, unique=True),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("last4", sa.String(4), nullable=False),
        sa.Column(
            "scopes",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "created_by_user_id",
            sa.String(40),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_ip", sa.String(45), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.String(40), nullable=True),
        sa.Column("ip_allowlist", sa.Text(), nullable=True),
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
        sa.CheckConstraint("environment IN ('test', 'live')", name="ck_api_keys_environment"),
    )
    op.create_index("ix_api_keys_org_env", "api_keys", ["organization_id", "environment"])
    op.create_index("ix_api_keys_prefix", "api_keys", ["key_prefix"])


def downgrade() -> None:
    op.drop_table("api_keys")
