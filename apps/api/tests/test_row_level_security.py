"""Postgres row-level security — the backstop under the repository layer.

Every other isolation test drives the application. These deliberately do not:
they issue raw SQL with **no `WHERE organization_id`**, which is exactly the
mistake RLS exists to survive. If the repository layer were removed entirely,
these are the guarantees that would remain.

Skipped on SQLite, which has no RLS. That is not a gap being waved away — it is
why the whole suite also runs against PostgreSQL in CI.

The role matters more than the policy. A superuser bypasses RLS unconditionally,
and `FORCE ROW LEVEL SECURITY` binds only the table *owner*. Running these as
`postgres` would pass every policy check and prove nothing, so they connect as
the unprivileged `fvas_app` role that production is meant to use.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import IS_POSTGRES, TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(
    not IS_POSTGRES, reason="row-level security is a PostgreSQL feature"
)

APP_ROLE = "fvas_app"


def _app_role_url() -> str:
    """The test database, reached as the unprivileged application role."""
    url = os.environ.get("TEST_APP_ROLE_URL")
    if url:
        return url
    # Swap the credentials in the configured test URL rather than hardcoding a
    # host, so this follows wherever the suite is pointed.
    _, _, rest = TEST_DATABASE_URL.partition("://")
    _, _, hostpart = rest.partition("@")
    return f"postgresql+asyncpg://{APP_ROLE}:{APP_ROLE}@{hostpart}"


@pytest.fixture
async def app_role_session(engine):  # type: ignore[no-untyped-def]
    """A session bound as `fvas_app`, over the schema the suite just created.

    Grants are issued by migration 0009, which the fixture-built schema does not
    run — so they are applied here against whatever tables exist. Skipping when
    the role is absent keeps a developer who has not migrated from seeing a
    confusing authentication error instead of a clear skip.
    """
    async with engine.begin() as connection:
        exists = await connection.scalar(
            text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": APP_ROLE}
        )
        if not exists:
            pytest.skip(f"role {APP_ROLE} does not exist; run `alembic upgrade head`")

        for table in (
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
        ):
            await connection.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            await connection.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
            await connection.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
            await connection.execute(
                text(
                    f"CREATE POLICY tenant_isolation ON {table} "
                    "USING (organization_id = current_setting('fvas.organization_id', true)) "
                    "WITH CHECK (organization_id = current_setting('fvas.organization_id', true))"
                )
            )

        await connection.execute(text("GRANT USAGE ON SCHEMA public TO fvas_app"))
        await connection.execute(
            text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO fvas_app")
        )
        await connection.execute(text("REVOKE UPDATE, DELETE ON audit_logs FROM fvas_app"))

    app_engine = create_async_engine(_app_role_url(), poolclass=NullPool)
    factory = async_sessionmaker(bind=app_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await app_engine.dispose()


@pytest.fixture
async def two_tenants_with_data(session):  # type: ignore[no-untyped-def]
    """Two organizations, one subject each, inserted as the owner."""
    from app.modules.biometrics.models import Subject
    from app.modules.identity.models import Organization

    session.add_all(
        [
            Organization(id="org_alpha", name="Alpha", slug="alpha"),
            Organization(id="org_beta", name="Beta", slug="beta"),
        ]
    )
    await session.flush()
    session.add_all(
        [
            Subject(id="sub_alpha", organization_id="org_alpha", external_id="alice"),
            Subject(id="sub_beta", organization_id="org_beta", external_id="bob"),
        ]
    )
    await session.commit()
    return "org_alpha", "org_beta"


async def _as_tenant(session, organization_id: str | None) -> None:  # type: ignore[no-untyped-def]
    await session.execute(
        text("SELECT set_config('fvas.organization_id', :org, false)"),
        {"org": organization_id or ""},
    )


async def test_an_unfiltered_query_sees_only_the_bound_tenant(
    app_role_session, two_tenants_with_data
) -> None:
    """The whole point. No `WHERE organization_id` anywhere in this query."""
    alpha, beta = two_tenants_with_data

    await _as_tenant(app_role_session, alpha)
    rows = list(await app_role_session.execute(text("SELECT organization_id FROM subjects")))
    assert [row[0] for row in rows] == [alpha]

    await _as_tenant(app_role_session, beta)
    rows = list(await app_role_session.execute(text("SELECT organization_id FROM subjects")))
    assert [row[0] for row in rows] == [beta]


async def test_no_tenant_bound_means_no_rows(app_role_session, two_tenants_with_data) -> None:
    """The policy fails **closed**.

    `current_setting(..., true)` yields NULL when unset, and NULL never equals a
    text column — so a forgotten `set_tenant` exposes nothing rather than
    everything. Failing open here would be worse than having no policy, because
    it would look like protection.
    """
    await _as_tenant(app_role_session, None)
    count = await app_role_session.scalar(text("SELECT count(*) FROM subjects"))
    assert count == 0


async def test_a_tenant_cannot_write_a_row_owned_by_another(
    app_role_session, two_tenants_with_data
) -> None:
    """`WITH CHECK` covers writes, not just reads.

    Without it a compromised tenant could plant rows in someone else's account —
    invisible to them, and fully visible to the victim.
    """
    alpha, beta = two_tenants_with_data
    await _as_tenant(app_role_session, beta)

    with pytest.raises((DBAPIError, ProgrammingError)) as error:
        await app_role_session.execute(
            text(
                "INSERT INTO subjects (id, organization_id, external_id, metadata, status,"
                " verification_count, created_at, updated_at)"
                " VALUES ('sub_forged', :org, 'forged', '{}', 'enrolled', 0, now(), now())"
            ),
            {"org": alpha},
        )
    assert "row-level security" in str(error.value).lower()


async def test_the_application_role_cannot_rewrite_the_audit_log(
    app_role_session, two_tenants_with_data
) -> None:
    """An audit log the application can rewrite proves nothing.

    Enforced by a grant, not a policy — the application has no `UPDATE` or
    `DELETE` on this table at all.
    """
    alpha, _ = two_tenants_with_data
    await _as_tenant(app_role_session, alpha)

    with pytest.raises((DBAPIError, ProgrammingError)) as error:
        await app_role_session.execute(text("DELETE FROM audit_logs"))
    assert "permission denied" in str(error.value).lower()


async def test_the_application_role_is_not_a_superuser(app_role_session) -> None:
    """The finding that made all of the above necessary.

    Migration 0008 enabled and forced RLS, and it protected nothing, because the
    stack connects as `postgres`. A superuser bypasses every policy
    unconditionally, and FORCE binds only the table owner. If this assertion
    ever fails, none of the other tests in this file mean anything.
    """
    row = await app_role_session.execute(
        text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    )
    is_superuser, bypasses_rls = row.one()
    assert is_superuser is False
    assert bypasses_rls is False
