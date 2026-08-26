"""row level security on the tenant data tables

Revision ID: 0008
Revises: 0007
Created: 2026-08-01

Defense in depth under the repository layer. If application code ever issues a
query without `WHERE organization_id = …`, the database returns nothing instead
of another customer's biometric data.

Two details decide whether this is real or theatre:

  * **FORCE.** Without `FORCE ROW LEVEL SECURITY`, the table owner bypasses
    every policy. The owner is the role that runs migrations, and in most
    single-role deployments it is also the role serving requests — so a policy
    without FORCE would test green and protect nothing.

  * **`current_setting(..., true)`.** The second argument makes a missing
    setting return NULL rather than raising. NULL never equals
    `organization_id`, so an unset tenant sees **no rows** — the policy fails
    closed. Failing open here would mean a forgotten `set_tenant` silently
    exposed everything.

The identity bootstrap tables (`users`, `memberships`, `roles`, `api_keys`,
`organizations`) deliberately carry no policy: they are read to determine which
tenant the caller belongs to, before any tenant is known. Policing them would
make authentication unable to resolve the very value the policy depends on.
See app/core/tenancy.py.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "subjects",
    "face_profiles",
    "face_templates",
    "enrollment_attempts",
    "verification_sessions",
    "usage_daily",
    "audit_logs",
    "webhook_endpoints",
    "webhook_deliveries",
    "org_settings",
)

SETTING = "fvas.organization_id"


def upgrade() -> None:
    # PostgreSQL only. SQLite has no RLS, and the fast test suite runs there —
    # which is precisely why the isolation tests also run against PostgreSQL.
    if op.get_bind().dialect.name != "postgresql":
        return

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (organization_id = current_setting('{SETTING}', true))
            WITH CHECK (organization_id = current_setting('{SETTING}', true))
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
