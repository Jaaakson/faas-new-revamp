"""Seed and verify the system roles and permissions.

The authorization decision is made from the in-code matrix in
`app.core.permissions`. These rows exist so the console can render a permission
matrix from data, and so tenant-defined custom roles become a data change later
rather than a schema change.

Because there are now two representations, they can drift. `assert_seed_matches`
runs at startup and refuses to serve if they do — which is the only thing that
makes keeping both honest.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import (
    ROLE_DESCRIPTIONS,
    ROLE_PERMISSIONS,
)
from app.core.permissions import (
    Permission as PermissionEnum,
)
from app.core.permissions import (
    Role as RoleEnum,
)
from app.modules.identity.models import Permission, Role, RolePermission

logger = structlog.get_logger(__name__)


async def seed_roles_and_permissions(session: AsyncSession) -> None:
    """Create or update the system roles and permissions. Idempotent."""
    existing_permissions = {
        permission.slug: permission
        for permission in (await session.execute(select(Permission))).scalars()
    }

    for enum_permission in PermissionEnum:
        if enum_permission.value in existing_permissions:
            continue
        resource, action = enum_permission.value.split(":", 1)
        permission = Permission(slug=enum_permission.value, resource=resource, action=action)
        session.add(permission)
        existing_permissions[enum_permission.value] = permission

    await session.flush()

    existing_roles = {
        role.slug: role
        for role in (
            await session.execute(select(Role).where(Role.organization_id.is_(None)))
        ).scalars()
    }

    for enum_role in RoleEnum:
        role = existing_roles.get(enum_role.value)
        if role is None:
            role = Role(
                slug=enum_role.value,
                name=enum_role.value.capitalize(),
                description=ROLE_DESCRIPTIONS[enum_role],
                is_system=True,
                organization_id=None,
            )
            session.add(role)
            await session.flush()
            existing_roles[enum_role.value] = role

        # Query the link rows rather than traversing `role.permissions`. On an
        # async session, attribute access on an unloaded relationship attempts
        # implicit IO outside the greenlet context and raises MissingGreenlet —
        # which is exactly what a freshly flushed object would do here.
        granted = set(
            await session.scalars(
                select(RolePermission.permission_id).where(RolePermission.role_id == role.id)
            )
        )
        for enum_permission in ROLE_PERMISSIONS[enum_role]:
            permission = existing_permissions[enum_permission.value]
            if permission.id not in granted:
                session.add(RolePermission(role_id=role.id, permission_id=permission.id))

    await session.flush()


async def assert_seed_matches(session: AsyncSession) -> None:
    """Fail loudly if the seeded rows and the code matrix disagree.

    Two sources of truth without a consistency check is how a console shows a
    permission the server does not actually grant.
    """
    permission_slugs = {slug for (slug,) in await session.execute(select(Permission.slug))}
    expected_slugs = {permission.value for permission in PermissionEnum}

    if permission_slugs != expected_slugs:
        missing = sorted(expected_slugs - permission_slugs)
        extra = sorted(permission_slugs - expected_slugs)
        raise RuntimeError(
            f"Permission table drifted from the code matrix. Missing: {missing}. Extra: {extra}"
        )

    roles = list(await session.scalars(select(Role).where(Role.organization_id.is_(None))))

    for role in roles:
        try:
            enum_role = RoleEnum(role.slug)
        except ValueError as exc:
            raise RuntimeError(f"Unknown system role in database: {role.slug}") from exc

        # Explicit join, for the same reason as in the seed above: traversing
        # `role.permissions` would attempt implicit IO on an async session.
        seeded = set(
            await session.scalars(
                select(Permission.slug)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role.id)
            )
        )
        expected = {permission.value for permission in ROLE_PERMISSIONS[enum_role]}
        if seeded != expected:
            raise RuntimeError(
                f"Role '{role.slug}' permissions drifted from the code matrix. "
                f"Missing: {sorted(expected - seeded)}. Extra: {sorted(seeded - expected)}"
            )

    logger.info("rbac_seed_verified", roles=len(RoleEnum), permissions=len(expected_slugs))


async def get_system_role(session: AsyncSession, slug: RoleEnum | str) -> Role:
    """Fetch a seeded system role by slug."""
    result = await session.execute(
        select(Role).where(Role.organization_id.is_(None), Role.slug == str(slug))
    )
    role = result.scalar_one_or_none()
    if role is None:
        raise RuntimeError(f"System role '{slug}' is missing. Run migrations and the RBAC seed.")
    return role
