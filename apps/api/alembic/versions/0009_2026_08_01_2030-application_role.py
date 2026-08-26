"""a non-superuser application role, so RLS is not theatre

Revision ID: 0009
Revises: 0008
Created: 2026-08-01

Migration 0008 enabled row-level security and forced it. That was necessary and
not sufficient: **superusers bypass RLS unconditionally**, and `FORCE ROW LEVEL
SECURITY` only binds the table *owner*, not a superuser.

The stack connects as `postgres`, which is a superuser. Verified directly:
with policies enabled and forced, tenant B could read tenant A's subjects *and*
insert a row owned by A. The policies were live and the protection was zero.

So RLS needs a role that is neither superuser nor table owner. This migration
creates one, grants it exactly the DML it needs, and nothing else:

  * no `BYPASSRLS`, no `SUPERUSER`, no `CREATEDB`, no `CREATEROLE`;
  * no `UPDATE` or `DELETE` on `audit_logs` — an audit log the application can
    rewrite proves nothing (docs/09-security.md §6);
  * no DDL, so a compromised application cannot drop its own policies.

Migrations keep running as the owner. That separation is the point: the role
that can change the schema is not the role that serves requests.

Set `DATABASE_URL` to this role in any environment where isolation matters.
Development keeps using `postgres` for convenience, which means **RLS is inert
in development** — stated plainly here rather than discovered later.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "fvas_app"

# Append-only. The application inserts and reads; it must not be able to alter
# history it wrote.
APPEND_ONLY_TABLES = ("audit_logs",)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    from sqlalchemy import text

    database = bind.execute(text("SELECT current_database()")).scalar()

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                -- NOSUPERUSER and NOBYPASSRLS are the whole point of this role.
                CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_ROLE}'
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT;
            END IF;
        END
        $$;
        """
    )

    op.execute(f'GRANT CONNECT ON DATABASE "{database}" TO {APP_ROLE}')
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}"
    )
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")

    # Tables created by later migrations inherit the same grants, so adding a
    # table does not silently leave the application unable to read it.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )

    for table in APPEND_ONLY_TABLES:
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM {APP_ROLE}")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    from sqlalchemy import text

    database = bind.execute(text("SELECT current_database()")).scalar()

    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE USAGE, SELECT ON SEQUENCES FROM {APP_ROLE}"
    )
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
    op.execute(f'REVOKE CONNECT ON DATABASE "{database}" FROM {APP_ROLE}')
    # The role itself is left in place: dropping it would fail if anything else
    # in the cluster still depends on it, and an orphan login role with no
    # grants can do nothing.
