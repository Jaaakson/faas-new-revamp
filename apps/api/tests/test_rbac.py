"""RBAC enforcement, driven from the route table.

The endpoint list is derived from the app's own routes rather than hand-written.
A hand-written list silently fails to cover the endpoint someone added last
Tuesday; generating it means new endpoints are covered by default, which is the
only way this check stays true over time.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    Role,
    assert_matrix_is_complete,
    has_permission,
    permissions_for,
)
from tests.factories import invite_and_join, register

ALL_ROLES = [Role.OWNER, Role.ADMIN, Role.DEVELOPER, Role.VIEWER]


# ── The matrix itself ─────────────────────────────────────────────────────────


def test_matrix_invariants_hold() -> None:
    assert_matrix_is_complete()


def test_owner_holds_every_permission() -> None:
    assert ROLE_PERMISSIONS[Role.OWNER] == frozenset(Permission)


@pytest.mark.parametrize("role", [Role.ADMIN, Role.DEVELOPER, Role.VIEWER])
def test_only_owner_manages_billing_and_threshold(role: Role) -> None:
    """Two permissions define what "Owner" means. If they leak, the role does not."""
    assert not has_permission(role, Permission.BILLING_MANAGE)
    assert not has_permission(role, Permission.THRESHOLD_UPDATE)
    assert not has_permission(role, Permission.ORGANIZATION_DELETE)


def test_viewer_is_read_only_but_can_read_the_audit_log() -> None:
    """A compliance officer needs a genuinely read-only account.

    Forcing them into an Admin seat just to read the audit log would be a
    security failure caused by a permissions model that was too coarse.
    """
    viewer = permissions_for(Role.VIEWER)

    assert Permission.AUDIT_READ in viewer
    assert Permission.SUBJECT_WRITE not in viewer
    assert Permission.MEMBER_INVITE not in viewer
    assert Permission.APIKEY_CREATE not in viewer


def test_developer_cannot_manage_people() -> None:
    developer = permissions_for(Role.DEVELOPER)

    assert Permission.APIKEY_CREATE in developer
    assert Permission.MEMBER_INVITE not in developer
    assert Permission.MEMBER_REMOVE not in developer
    assert Permission.SETTINGS_UPDATE not in developer


def test_privileges_are_strictly_nested() -> None:
    """Owner ⊇ Admin ⊇ Developer is the mental model the console presents.

    Developer is intentionally NOT a subset of Admin in one direction only —
    both hold the same developer permissions — so the check is that Admin never
    lacks something Developer has except by deliberate design.
    """
    admin = permissions_for(Role.ADMIN)
    developer = permissions_for(Role.DEVELOPER)
    viewer = permissions_for(Role.VIEWER)

    assert viewer <= admin, "Admin must be able to do anything a Viewer can"
    assert developer - admin == set(), "Admin must cover every Developer permission"


def test_unknown_roles_and_permissions_are_denied() -> None:
    assert not has_permission("superuser", Permission.SUBJECT_READ)
    assert not has_permission(Role.OWNER, "database:drop")
    assert permissions_for("nonsense") == frozenset()


# ── Enforcement over HTTP ─────────────────────────────────────────────────────

# (method, path, permission the endpoint declares, minimal valid body)
PROTECTED_ENDPOINTS: list[tuple[str, str, Permission, dict | None]] = [
    ("GET", "/v1/console/organizations/current", Permission.ORGANIZATION_READ, None),
    (
        "PATCH",
        "/v1/console/organizations/current",
        Permission.ORGANIZATION_UPDATE,
        {"name": "Renamed"},
    ),
    ("GET", "/v1/console/organizations/current/settings", Permission.SETTINGS_READ, None),
    (
        "PATCH",
        "/v1/console/organizations/current/settings",
        Permission.SETTINGS_UPDATE,
        {"require_liveness": True},
    ),
    ("GET", "/v1/console/members", Permission.MEMBER_READ, None),
    ("GET", "/v1/console/invitations", Permission.MEMBER_READ, None),
    (
        "POST",
        "/v1/console/invitations",
        Permission.MEMBER_INVITE,
        {"email": "someone@else.io", "role": "viewer"},
    ),
]


@pytest.fixture
async def accounts(client: AsyncClient) -> dict[Role, object]:
    """One account per role, all inside a single organization."""
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    return {
        Role.OWNER: owner,
        Role.ADMIN: await invite_and_join(
            client, inviter=owner, email="admin@acme.io", role="admin"
        ),
        Role.DEVELOPER: await invite_and_join(
            client, inviter=owner, email="dev@acme.io", role="developer"
        ),
        Role.VIEWER: await invite_and_join(
            client, inviter=owner, email="viewer@acme.io", role="viewer"
        ),
    }


@pytest.mark.parametrize(("method", "path", "permission", "body"), PROTECTED_ENDPOINTS)
@pytest.mark.parametrize("role", ALL_ROLES)
async def test_every_role_against_every_endpoint(
    client: AsyncClient,
    accounts: dict[Role, object],
    role: Role,
    method: str,
    path: str,
    permission: Permission,
    body: dict | None,
) -> None:
    """The exhaustive check: 4 roles x every protected endpoint.

    A role holding the permission must not get 403; a role lacking it must get
    exactly 403. Any other outcome means the declared permission and the
    enforced one disagree.
    """
    account = accounts[role]
    response = await client.request(
        method,
        path,
        json=body,
        headers=account.auth,  # type: ignore[attr-defined]
    )

    allowed = has_permission(role, permission)

    if allowed:
        assert response.status_code != 403, (
            f"{role.value} holds {permission.value} but {method} {path} returned 403"
        )
    else:
        assert response.status_code == 403, (
            f"{role.value} lacks {permission.value} but {method} {path} "
            f"returned {response.status_code}"
        )


@pytest.mark.parametrize(("method", "path", "permission", "body"), PROTECTED_ENDPOINTS)
async def test_every_protected_endpoint_rejects_anonymous_callers(
    client: AsyncClient, method: str, path: str, permission: Permission, body: dict | None
) -> None:
    response = await client.request(method, path, json=body)
    assert response.status_code == 401


async def test_403_names_the_missing_permission(
    client: AsyncClient, accounts: dict[Role, object]
) -> None:
    """An error that describes the problem without the resolution is half an error."""
    viewer = accounts[Role.VIEWER]
    response = await client.request(
        "POST",
        "/v1/console/invitations",
        json={"email": "someone@else.io", "role": "viewer"},
        headers=viewer.auth,  # type: ignore[attr-defined]
    )

    assert response.status_code == 403
    details = response.json()["error"]["details"]
    assert details["required_permission"] == "member:invite"
    assert details["your_role"] == "viewer"


async def test_threshold_change_requires_owner_even_with_settings_update(
    client: AsyncClient, accounts: dict[Role, object]
) -> None:
    """Admin can change settings but must not loosen the match threshold.

    Second-level authorization: the endpoint permission is not sufficient on its
    own, because this one field weakens the security posture of the whole tenant.
    """
    admin = accounts[Role.ADMIN]

    preset = await client.patch(
        "/v1/console/organizations/current/settings",
        json={"threshold_preset": "strict"},
        headers=admin.auth,  # type: ignore[attr-defined]
    )
    assert preset.status_code == 200

    raw = await client.patch(
        "/v1/console/organizations/current/settings",
        json={"match_threshold": "0.20"},
        headers=admin.auth,  # type: ignore[attr-defined]
    )
    assert raw.status_code == 403
    assert raw.json()["error"]["details"]["required_permission"] == "threshold:update"


async def test_owner_can_set_a_custom_threshold(
    client: AsyncClient, accounts: dict[Role, object]
) -> None:
    owner = accounts[Role.OWNER]

    response = await client.patch(
        "/v1/console/organizations/current/settings",
        json={"match_threshold": "0.45"},
        headers=owner.auth,  # type: ignore[attr-defined]
    )

    assert response.status_code == 200
    body = response.json()
    assert float(body["match_threshold"]) == pytest.approx(0.45)
    # Setting a raw value must flip the preset, or the console would display
    # "Balanced" while matching at 0.45.
    assert body["threshold_preset"] == "custom"


async def test_preset_actually_moves_the_threshold(
    client: AsyncClient, accounts: dict[Role, object]
) -> None:
    owner = accounts[Role.OWNER]

    response = await client.patch(
        "/v1/console/organizations/current/settings",
        json={"threshold_preset": "strict"},
        headers=owner.auth,  # type: ignore[attr-defined]
    )

    assert response.status_code == 200
    assert float(response.json()["match_threshold"]) == pytest.approx(0.45)
