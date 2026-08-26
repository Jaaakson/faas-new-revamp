"""The RBAC matrix.

Authorization resolves from this in-code table, not from a per-request join.
For four fixed roles a database round-trip on every authorization check would be
pure cost. The `roles`/`permissions`/`role_permissions` tables still exist and
are seeded from this module, so custom roles later become a data change rather
than a schema change — and a startup assertion verifies the two never diverge
(docs/06-database.md §4.1).
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class Permission(StrEnum):
    """`resource:action`. Kept exhaustive so a typo is an import error."""

    ORGANIZATION_READ = "organization:read"
    ORGANIZATION_UPDATE = "organization:update"
    ORGANIZATION_DELETE = "organization:delete"

    MEMBER_READ = "member:read"
    MEMBER_INVITE = "member:invite"
    MEMBER_UPDATE_ROLE = "member:update_role"
    MEMBER_REMOVE = "member:remove"

    APIKEY_READ = "apikey:read"
    APIKEY_CREATE = "apikey:create"
    APIKEY_REVOKE = "apikey:revoke"

    SUBJECT_READ = "subject:read"
    SUBJECT_WRITE = "subject:write"
    SUBJECT_DELETE = "subject:delete"

    ENROLLMENT_WRITE = "enrollment:write"
    VERIFICATION_WRITE = "verification:write"
    VERIFICATION_READ = "verification:read"

    SETTINGS_READ = "settings:read"
    SETTINGS_UPDATE = "settings:update"
    THRESHOLD_UPDATE = "threshold:update"

    WEBHOOK_MANAGE = "webhook:manage"
    AUDIT_READ = "audit:read"
    BILLING_MANAGE = "billing:manage"


# Mirrors the table in docs/09-security.md §3. That document is the spec; if the
# two disagree, one of them is a bug.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: frozenset(Permission),  # every permission, by definition
    Role.ADMIN: frozenset(
        {
            Permission.ORGANIZATION_READ,
            Permission.ORGANIZATION_UPDATE,
            Permission.MEMBER_READ,
            Permission.MEMBER_INVITE,
            Permission.MEMBER_UPDATE_ROLE,
            Permission.MEMBER_REMOVE,
            Permission.APIKEY_READ,
            Permission.APIKEY_CREATE,
            Permission.APIKEY_REVOKE,
            Permission.SUBJECT_READ,
            Permission.SUBJECT_WRITE,
            Permission.SUBJECT_DELETE,
            Permission.ENROLLMENT_WRITE,
            Permission.VERIFICATION_WRITE,
            Permission.VERIFICATION_READ,
            Permission.SETTINGS_READ,
            Permission.SETTINGS_UPDATE,
            Permission.WEBHOOK_MANAGE,
            Permission.AUDIT_READ,
        }
    ),
    Role.DEVELOPER: frozenset(
        {
            Permission.ORGANIZATION_READ,
            Permission.MEMBER_READ,
            Permission.APIKEY_READ,
            Permission.APIKEY_CREATE,
            Permission.APIKEY_REVOKE,
            Permission.SUBJECT_READ,
            Permission.SUBJECT_WRITE,
            Permission.ENROLLMENT_WRITE,
            Permission.VERIFICATION_WRITE,
            Permission.VERIFICATION_READ,
            Permission.SETTINGS_READ,
            Permission.WEBHOOK_MANAGE,
        }
    ),
    Role.VIEWER: frozenset(
        {
            Permission.ORGANIZATION_READ,
            Permission.MEMBER_READ,
            Permission.SUBJECT_READ,
            Permission.VERIFICATION_READ,
            Permission.SETTINGS_READ,
            # A compliance officer needs a genuinely read-only account. Forcing
            # them into an Admin seat just to read the audit log would be a
            # security failure caused by a permissions model that was too coarse.
            Permission.AUDIT_READ,
        }
    ),
}

ROLE_DESCRIPTIONS: dict[Role, str] = {
    Role.OWNER: "Full control, including billing, deletion, and the match threshold.",
    Role.ADMIN: "Manage members, keys, subjects, and settings. Cannot change billing.",
    Role.DEVELOPER: "Integrate and operate: keys, subjects, enrollment, verification.",
    Role.VIEWER: "Read-only, including the audit log. For compliance and oversight.",
}


def has_permission(role: Role | str, permission: Permission | str) -> bool:
    """Check a role against the matrix. Unknown roles are denied."""
    try:
        resolved_role = Role(role)
        resolved_permission = Permission(permission)
    except ValueError:
        return False
    return resolved_permission in ROLE_PERMISSIONS[resolved_role]


def permissions_for(role: Role | str) -> frozenset[Permission]:
    try:
        return ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return frozenset()


def assert_matrix_is_complete() -> None:
    """Guard the invariants the matrix must satisfy. Called at startup.

    Cheap, and it catches the two mistakes that are otherwise invisible: a new
    permission that nobody can use, and a role that silently outranks Owner.
    """
    owner_permissions = ROLE_PERMISSIONS[Role.OWNER]

    for role in Role:
        if role not in ROLE_PERMISSIONS:
            raise RuntimeError(f"Role {role} has no entry in the permission matrix")

    # Owner is the ceiling. Any permission held by another role but not by
    # Owner would make Owner not actually the most privileged role.
    for role, granted in ROLE_PERMISSIONS.items():
        if role is Role.OWNER:
            continue
        escalated = granted - owner_permissions
        if escalated:
            raise RuntimeError(
                f"Role {role} holds permissions Owner does not: "
                f"{sorted(p.value for p in escalated)}"
            )

    # A permission no role can exercise is dead code at best and a forgotten
    # grant at worst.
    unreachable = set(Permission) - set().union(*ROLE_PERMISSIONS.values())
    if unreachable:
        raise RuntimeError(
            f"Permissions granted to no role: {sorted(p.value for p in unreachable)}"
        )
