"""Postgres row-level security — the backstop under the repository layer.

Tenancy already has three defences: `TenantScopedRepository` injects the filter
structurally, composite indexes lead with `organization_id`, and a generated
test drives every id-addressed route across a tenant boundary. RLS is the fourth
and the only one that survives a mistake in the other three. If someone writes a
raw query and forgets the filter, the database returns nothing rather than
someone else's biometric data.

**Which tables carry a policy, and which deliberately do not.**

Applied to the customer *data* tables — subjects, profiles, templates,
enrollment attempts, verification sessions, usage rollups, audit logs, webhooks.

Not applied to the identity *bootstrap* tables — `users`, `memberships`,
`roles`, `api_keys`. Those are read to work out **who the caller is and which
tenant they belong to**, which happens before any tenant is known. A policy
there would make authentication unable to authenticate: the membership lookup
that resolves the organization would itself be filtered by the organization it
is trying to resolve. They stay protected by the service layer, which is the
only layer that can protect them.

`FORCE ROW LEVEL SECURITY` matters. Without it, the table owner — which in most
deployments is the role running migrations, and in development is the role
running everything — silently bypasses every policy, and the protection is
theatre that tests green.

The tenant is carried in a session GUC set with `SET LOCAL`, so it is scoped to
the transaction and cannot leak to the next request that borrows the same
pooled connection.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

#: Tables whose every row belongs to exactly one tenant.
RLS_TABLES: tuple[str, ...] = (
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

#: Read before the tenant is known, so they cannot carry a policy. See above.
BOOTSTRAP_TABLES: tuple[str, ...] = (
    "users",
    "memberships",
    "roles",
    "permissions",
    "role_permissions",
    "api_keys",
    "organizations",
    "invitations",
    "refresh_tokens",
    "password_reset_tokens",
    "auth_logs",
)

TENANT_SETTING = "fvas.organization_id"


async def set_tenant(session: AsyncSession, organization_id: str | None) -> None:
    """Bind this transaction to a tenant.

    `SET LOCAL` rather than `SET`: the value is reverted when the transaction
    ends, so a pooled connection cannot carry one request's tenant into the
    next. That failure mode is exactly the cross-tenant leak RLS exists to
    prevent, and it would be invisible under low load.

    A no-op on SQLite, which has no RLS. The fast test suite therefore proves
    the *application's* isolation; the PostgreSQL run proves the database's.
    """
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return

    # Parameter binding is not available for SET, so the value is quoted through
    # `set_config`, which takes it as a real parameter and cannot be injected.
    await session.execute(
        text(f"SELECT set_config('{TENANT_SETTING}', :org, true)"),
        {"org": organization_id or ""},
    )


async def current_tenant(session: AsyncSession) -> str | None:
    """Read back the bound tenant. Used by tests and diagnostics."""
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return None
    value = await session.scalar(text(f"SELECT current_setting('{TENANT_SETTING}', true)"))
    return value or None
