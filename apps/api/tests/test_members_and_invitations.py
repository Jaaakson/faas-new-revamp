"""Membership management and the invariants that keep an organization usable."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import invite_and_join, login, register

MEMBERS = "/v1/console/members"
INVITATIONS = "/v1/console/invitations"


# ── The last-Owner invariant ──────────────────────────────────────────────────


async def test_the_last_owner_cannot_be_demoted(client: AsyncClient) -> None:
    """Without this an organization is orphaned.

    Nobody could manage billing, change the threshold, or invite a replacement,
    and no support path short of direct database access could fix it.
    """
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    members = (await client.get(MEMBERS, headers=owner.auth)).json()
    own_membership = members[0]["id"]

    response = await client.patch(
        f"{MEMBERS}/{own_membership}", json={"role": "admin"}, headers=owner.auth
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_owner"


async def test_the_last_owner_cannot_be_removed(client: AsyncClient) -> None:
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    members = (await client.get(MEMBERS, headers=owner.auth)).json()

    response = await client.delete(f"{MEMBERS}/{members[0]['id']}", headers=owner.auth)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_owner"


async def test_an_owner_can_step_down_once_another_exists(client: AsyncClient) -> None:
    """The invariant is "at least one Owner", not "Owners are permanent"."""
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    await invite_and_join(client, inviter=owner, email="second@acme.io", role="owner")

    members = (await client.get(MEMBERS, headers=owner.auth)).json()
    original = next(m for m in members if m["email"] == "owner@acme.io")

    response = await client.patch(
        f"{MEMBERS}/{original['id']}", json={"role": "admin"}, headers=owner.auth
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"


async def test_a_demoted_owner_immediately_loses_owner_powers(
    client: AsyncClient,
) -> None:
    """Authorization must reflect the current membership, not the issued token.

    The access token still carries `role: owner`, so this only passes because
    the principal re-reads membership on every request.
    """
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    await invite_and_join(client, inviter=owner, email="second@acme.io", role="owner")

    members = (await client.get(MEMBERS, headers=owner.auth)).json()
    original = next(m for m in members if m["email"] == "owner@acme.io")
    await client.patch(f"{MEMBERS}/{original['id']}", json={"role": "viewer"}, headers=owner.auth)

    # Same token as before the demotion.
    response = await client.post(
        INVITATIONS, json={"email": "third@acme.io", "role": "viewer"}, headers=owner.auth
    )

    assert response.status_code == 403


# ── Admin limits ──────────────────────────────────────────────────────────────


async def test_an_admin_cannot_change_an_owners_role(client: AsyncClient) -> None:
    """An Admin manages the team but must not touch the person who can remove them."""
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    admin = await invite_and_join(client, inviter=owner, email="admin@acme.io", role="admin")

    members = (await client.get(MEMBERS, headers=admin.auth)).json()
    owner_membership = next(m for m in members if m["role"] == "owner")

    response = await client.patch(
        f"{MEMBERS}/{owner_membership['id']}", json={"role": "viewer"}, headers=admin.auth
    )

    assert response.status_code == 403


async def test_an_admin_cannot_remove_an_owner(client: AsyncClient) -> None:
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    admin = await invite_and_join(client, inviter=owner, email="admin@acme.io", role="admin")

    members = (await client.get(MEMBERS, headers=admin.auth)).json()
    owner_membership = next(m for m in members if m["role"] == "owner")

    response = await client.delete(f"{MEMBERS}/{owner_membership['id']}", headers=admin.auth)

    assert response.status_code == 403


async def test_an_admin_cannot_promote_someone_to_owner(client: AsyncClient) -> None:
    """Otherwise Admin is Owner with extra steps."""
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    admin = await invite_and_join(client, inviter=owner, email="admin@acme.io", role="admin")
    await invite_and_join(client, inviter=owner, email="dev@acme.io", role="developer")

    members = (await client.get(MEMBERS, headers=admin.auth)).json()
    developer = next(m for m in members if m["email"] == "dev@acme.io")

    response = await client.patch(
        f"{MEMBERS}/{developer['id']}", json={"role": "owner"}, headers=admin.auth
    )

    assert response.status_code == 403


async def test_an_admin_cannot_invite_an_owner(client: AsyncClient) -> None:
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    admin = await invite_and_join(client, inviter=owner, email="admin@acme.io", role="admin")

    response = await client.post(
        INVITATIONS, json={"email": "new@acme.io", "role": "owner"}, headers=admin.auth
    )

    assert response.status_code == 403


async def test_an_admin_can_manage_ordinary_members(client: AsyncClient) -> None:
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    admin = await invite_and_join(client, inviter=owner, email="admin@acme.io", role="admin")
    await invite_and_join(client, inviter=owner, email="dev@acme.io", role="developer")

    members = (await client.get(MEMBERS, headers=admin.auth)).json()
    developer = next(m for m in members if m["email"] == "dev@acme.io")

    promoted = await client.patch(
        f"{MEMBERS}/{developer['id']}", json={"role": "admin"}, headers=admin.auth
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"

    removed = await client.delete(f"{MEMBERS}/{developer['id']}", headers=admin.auth)
    assert removed.status_code == 200


# ── Invitations ───────────────────────────────────────────────────────────────


async def test_an_invited_user_joins_the_inviting_organization(
    client: AsyncClient,
) -> None:
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    invited = await invite_and_join(client, inviter=owner, email="dev@acme.io", role="developer")

    me = (await client.get("/v1/console/auth/me", headers=invited.auth)).json()

    # Joining via an invite must NOT also create a personal organization.
    assert len(me["organizations"]) == 1
    assert me["organizations"][0]["name"] == "Acme Corp"
    assert me["organizations"][0]["role"] == "developer"


async def test_an_invitation_cannot_be_redirected_to_another_address(
    client: AsyncClient,
) -> None:
    """The email is bound to the token; otherwise a leaked link is an open door."""
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    created = await client.post(
        INVITATIONS, json={"email": "intended@acme.io", "role": "viewer"}, headers=owner.auth
    )
    token = created.json()["token"]

    response = await client.post(
        "/v1/console/auth/register",
        json={
            "email": "attacker@evil.io",
            "password": "correct-horse-battery-staple",
            "full_name": "Attacker",
            "invitation_token": token,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invitation_email_mismatch"


async def test_a_revoked_invitation_cannot_be_used(client: AsyncClient) -> None:
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    created = await client.post(
        INVITATIONS, json={"email": "dev@acme.io", "role": "viewer"}, headers=owner.auth
    )
    body = created.json()

    await client.delete(f"{INVITATIONS}/{body['id']}", headers=owner.auth)

    response = await client.post(
        "/v1/console/auth/register",
        json={
            "email": "dev@acme.io",
            "password": "correct-horse-battery-staple",
            "full_name": "Dev",
            "invitation_token": body["token"],
        },
    )
    assert response.status_code == 400


async def test_revoking_frees_the_address_to_be_invited_again(
    client: AsyncClient,
) -> None:
    """The pending-unique index is partial for exactly this reason.

    A full unique index would permanently block re-inviting someone whose
    invitation was revoked.
    """
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    first = await client.post(
        INVITATIONS, json={"email": "dev@acme.io", "role": "viewer"}, headers=owner.auth
    )
    await client.delete(f"{INVITATIONS}/{first.json()['id']}", headers=owner.auth)

    second = await client.post(
        INVITATIONS, json={"email": "dev@acme.io", "role": "admin"}, headers=owner.auth
    )

    assert second.status_code == 201


async def test_a_duplicate_pending_invitation_is_rejected(client: AsyncClient) -> None:
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    await client.post(
        INVITATIONS, json={"email": "dev@acme.io", "role": "viewer"}, headers=owner.auth
    )

    duplicate = await client.post(
        INVITATIONS, json={"email": "dev@acme.io", "role": "viewer"}, headers=owner.auth
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "invitation_pending"


async def test_inviting_an_existing_member_is_rejected(client: AsyncClient) -> None:
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    await invite_and_join(client, inviter=owner, email="dev@acme.io", role="developer")

    response = await client.post(
        INVITATIONS, json={"email": "dev@acme.io", "role": "admin"}, headers=owner.auth
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_member"


async def test_invitation_preview_is_public_but_minimal(client: AsyncClient) -> None:
    """The recipient may not have an account yet, so preview is unauthenticated.

    It must therefore reveal as little as possible about the tenant.
    """
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    created = await client.post(
        INVITATIONS, json={"email": "dev@acme.io", "role": "developer"}, headers=owner.auth
    )
    token = created.json()["token"]

    response = await client.get(f"{INVITATIONS}/preview/{token}")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "organization_name": "Acme Corp",
        "email": "dev@acme.io",
        "role": "developer",
        "expires_at": body["expires_at"],
    }


async def test_preview_of_an_unknown_token_is_a_404(client: AsyncClient) -> None:
    response = await client.get(f"{INVITATIONS}/preview/not-a-real-token")
    assert response.status_code == 404


async def test_an_existing_user_can_accept_an_invitation(client: AsyncClient) -> None:
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    outsider = await register(client, email="outsider@other.io", organization_name="Other Co")

    created = await client.post(
        INVITATIONS,
        json={"email": "outsider@other.io", "role": "developer"},
        headers=owner.auth,
    )

    accepted = await client.post(
        f"{INVITATIONS}/accept",
        json={"token": created.json()["token"]},
        headers=outsider.auth,
    )
    assert accepted.status_code == 200

    me = (await client.get("/v1/console/auth/me", headers=outsider.auth)).json()
    assert {org["name"] for org in me["organizations"]} == {"Other Co", "Acme Corp"}


async def test_accepting_someone_elses_invitation_is_forbidden(
    client: AsyncClient,
) -> None:
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    outsider = await register(client, email="outsider@other.io", organization_name="Other Co")
    created = await client.post(
        INVITATIONS, json={"email": "someone@else.io", "role": "viewer"}, headers=owner.auth
    )

    response = await client.post(
        f"{INVITATIONS}/accept",
        json={"token": created.json()["token"]},
        headers=outsider.auth,
    )

    assert response.status_code == 403


# ── Organization switching ────────────────────────────────────────────────────


async def test_login_can_select_an_organization(client: AsyncClient) -> None:
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    second = await client.post(
        "/v1/console/organizations", json={"name": "Side Project"}, headers=owner.auth
    )
    second_id = second.json()["id"]

    response = await client.post(
        "/v1/console/auth/login",
        json={
            "email": "owner@acme.io",
            "password": "correct-horse-battery-staple",
            "organization_id": second_id,
        },
    )

    assert response.status_code == 200
    assert response.json()["organization"]["name"] == "Side Project"


async def test_login_defaults_to_the_first_organization(client: AsyncClient) -> None:
    owner = await register(client, email="owner@acme.io", organization_name="Acme Corp")
    await client.post(
        "/v1/console/organizations", json={"name": "Side Project"}, headers=owner.auth
    )

    session = await login(client, email="owner@acme.io")

    assert session.organization_id == owner.organization_id


@pytest.mark.parametrize("role", ["owner", "admin", "developer", "viewer"])
async def test_every_role_can_be_invited(client: AsyncClient, role: str) -> None:
    owner = await register(client, email="founder@acme.io", organization_name="Acme Corp")

    # Distinct from the founder's address: inviting an existing member is a
    # separate (and correctly rejected) case, covered above.
    invited = await invite_and_join(
        client, inviter=owner, email=f"invited-{role}@acme.io", role=role
    )

    me = (await client.get("/v1/console/auth/me", headers=invited.auth)).json()
    assert me["organizations"][0]["role"] == role
