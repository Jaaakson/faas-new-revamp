"""Cross-tenant isolation, driven from the app's own route table.

Shared-schema tenancy lives or dies on the tenant filter never being forgotten.
The endpoint list is *generated* from the mounted routes rather than written by
hand, so an endpoint added later is covered by default. A hand-maintained list
silently fails to cover exactly the endpoint nobody remembered to add.

The rule under test: a resource belonging to another tenant must be
indistinguishable from one that does not exist. A 403 would confirm existence
and leak information across the boundary.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.main import create_app
from tests.factories import create_subject, enroll, frame, frames, register

# Routes that are deliberately not tenant-scoped.
_NOT_TENANT_SCOPED = {
    "/health",
    "/ready",
    "/v1/console/auth/register",
    "/v1/console/auth/login",
    "/v1/console/auth/refresh",
    "/v1/console/auth/logout",
    "/v1/console/auth/verify-email",
    "/v1/console/auth/forgot-password",
    "/v1/console/auth/reset-password",
    "/v1/console/auth/change-password",
    "/v1/console/auth/me",
    "/v1/console/auth/session-policy",
    # Creating an organization is how a user gets their first tenant.
    "/v1/console/organizations",
    # Accepting or previewing an invite is cross-tenant by design — that is the
    # entire mechanism for joining a new organization.
    "/v1/console/invitations/accept",
    "/v1/console/invitations/preview/{token}",
}


def _tenant_scoped_routes() -> list[tuple[str, str]]:
    """Every mounted route that should be confined to one tenant."""
    schema = create_app().openapi()
    routes: list[tuple[str, str]] = []
    for path, operations in schema["paths"].items():
        if path in _NOT_TENANT_SCOPED:
            continue
        for method in operations:
            if method.upper() in {"GET", "POST", "PATCH", "DELETE"}:
                routes.append((method.upper(), path))
    return sorted(routes)


TENANT_SCOPED_ROUTES = _tenant_scoped_routes()

# Routes carrying a resource id in the path — the ones where a cross-tenant
# lookup is actually possible.
PARAMETERISED_ROUTES = [(method, path) for method, path in TENANT_SCOPED_ROUTES if "{" in path]


def test_the_generator_found_routes() -> None:
    """A generator that silently matches nothing proves nothing."""
    assert TENANT_SCOPED_ROUTES, "no tenant-scoped routes discovered"
    assert PARAMETERISED_ROUTES, "no parameterised routes discovered"


@pytest.fixture
async def two_tenants(client: AsyncClient):  # type: ignore[no-untyped-def]
    """Two organizations that must never see each other."""
    alice = await register(client, email="alice@one.io", organization_name="Tenant One")
    bob = await register(client, email="bob@two.io", organization_name="Tenant Two")
    assert alice.organization_id != bob.organization_id
    return alice, bob


# A schema-valid body per route. Without one, request validation returns 400
# *before* the tenant lookup runs — the assertion would pass on the wrong code
# path and the isolation check would never actually execute.
VALID_BODIES: dict[tuple[str, str], dict] = {
    ("PATCH", "/v1/console/members/{membership_id}"): {"role": "viewer"},
    ("PATCH", "/v1/console/subjects/{subject_id}"): {"display_name": "Renamed"},
    ("PATCH", "/v1/console/webhooks/{endpoint_id}"): {"description": "Renamed"},
}


@pytest.mark.parametrize(("method", "path"), PARAMETERISED_ROUTES)
async def test_cross_tenant_resource_ids_return_404(
    client: AsyncClient, two_tenants, session, method: str, path: str
) -> None:
    """Every id-addressed endpoint, exercised across the tenant boundary."""
    alice, bob = two_tenants

    # Build a real resource in Alice's tenant for each parameterised route.
    resource_id = await _create_resource_for(client, alice, path, session)
    if resource_id is None:
        pytest.skip(f"no fixture available for {path}")

    concrete = path
    for name in (
        "membership_id",
        "invitation_id",
        "subject_id",
        "enrollment_id",
        "verification_id",
        "endpoint_id",
        "key_id",
    ):
        concrete = concrete.replace(f"{{{name}}}", resource_id)

    if "webhook" in path:
        # Bob must also be on a paid plan, or the route would 403 on billing
        # before it ever reached the tenant check.
        from app.modules.identity.models import Organization

        bob_org = await session.get(Organization, bob.organization_id)
        assert bob_org is not None
        bob_org.plan = "growth"
        await session.commit()

    # The public plane takes an API key, not a JWT. Sending Bob's console token
    # there would be rejected as unauthenticated *before* the tenant lookup, so
    # the assertion would pass without ever testing isolation.
    headers = await _api_key_headers(client, bob, session) if _is_public(path) else bob.auth

    body = VALID_BODIES.get((method, path), {})
    response = await client.request(method, concrete, json=body, headers=headers)

    assert response.status_code != 400, (
        f"{method} {path} failed validation before reaching the tenant check — "
        f"add a valid body to VALID_BODIES so this route is actually exercised"
    )
    assert response.status_code == 404, (
        f"{method} {path} leaked across tenants with {response.status_code}; "
        "another tenant's resource must be indistinguishable from a missing one"
    )


def _is_public(path: str) -> bool:
    """A `/v1` path that is not under `/v1/console`."""
    return path.startswith("/v1/") and not path.startswith("/v1/console/")


async def _api_key_headers(client: AsyncClient, account, db_session) -> dict[str, str]:
    """Mint a full-scope key for `account` and return its Authorization header.

    Full scope on purpose: a key that lacked the scope would 403 before the
    tenant check, which is the same blind spot as sending the wrong credential
    type.
    """
    from tests.factories import mark_email_verified

    await mark_email_verified(db_session, account)
    created = await client.post(
        "/v1/console/api-keys",
        json={
            "name": "isolation probe",
            "environment": "test",
            "scopes": [
                "subject:read",
                "subject:write",
                "subject:delete",
                "enrollment:write",
                "verification:write",
                "verification:read",
            ],
        },
        headers=account.auth,
    )
    assert created.status_code == 201, created.text
    return {"Authorization": f"Bearer {created.json()['secret']}"}


async def _create_resource_for(client: AsyncClient, owner, path: str, db_session) -> str | None:
    """Create a resource of the type `path` addresses, inside owner's tenant."""
    if "{membership_id}" in path:
        members = await client.get("/v1/console/members", headers=owner.auth)
        return members.json()[0]["id"]

    if "{invitation_id}" in path:
        created = await client.post(
            "/v1/console/invitations",
            json={"email": "invitee@one.io", "role": "viewer"},
            headers=owner.auth,
        )
        return created.json()["id"]

    if "{subject_id}" in path:
        # Enrolled, not bare: the face-profile routes need a profile to exist,
        # or they would answer 404 for the wrong reason and the isolation
        # assertion would pass without testing isolation.
        subject = await create_subject(client, owner, external_id="isolation_probe")
        response = await enroll(client, owner, subject["id"], images=frames(7, 3))
        assert response.status_code == 201, response.text
        return str(subject["id"])

    if "{endpoint_id}" in path:
        # Webhooks need a paid plan, so upgrade the owner's org first. Testing
        # isolation on a route that 403s for a different reason would prove
        # nothing.
        from app.modules.identity.models import Organization

        organization = await db_session.get(Organization, owner.organization_id)
        assert organization is not None
        organization.plan = "growth"
        await db_session.commit()

        created = await client.post(
            "/v1/console/webhooks",
            json={"url": "https://hooks.example.com/x", "events": ["verification.completed"]},
            headers=owner.auth,
        )
        assert created.status_code == 201, created.text
        return str(created.json()["id"])

    if "{key_id}" in path:
        from tests.factories import mark_email_verified

        await mark_email_verified(db_session, owner)
        created = await client.post(
            "/v1/console/api-keys",
            json={"name": "isolation target", "environment": "test"},
            headers=owner.auth,
        )
        assert created.status_code == 201, created.text
        return str(created.json()["id"])

    if _is_public(path) and "{subject_id}" in path:
        subject = await create_subject(client, owner, external_id="public_isolation")
        enrolled = await enroll(client, owner, subject["id"], images=frames(12, 3))
        assert enrolled.status_code == 201, enrolled.text
        return str(subject["id"])

    if "{verification_id}" in path:
        subject = await create_subject(client, owner, external_id="isolation_verification")
        enrolled = await enroll(client, owner, subject["id"], images=frames(9, 3))
        assert enrolled.status_code == 201, enrolled.text
        response = await client.post(
            "/v1/console/verifications",
            json={"subject_id": subject["id"], "image": frame(9, seed=99)},
            headers=owner.auth,
        )
        assert response.status_code == 200, response.text
        return str(response.json()["id"])

    if "{enrollment_id}" in path:
        subject = await create_subject(client, owner, external_id="isolation_enrollment")
        response = await enroll(client, owner, subject["id"], images=frames(8, 3))
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    return None


# ── Data-level isolation ──────────────────────────────────────────────────────


async def test_members_list_never_includes_another_tenant(client: AsyncClient, two_tenants) -> None:
    alice, bob = two_tenants

    alice_members = (await client.get("/v1/console/members", headers=alice.auth)).json()
    bob_members = (await client.get("/v1/console/members", headers=bob.auth)).json()

    assert [m["email"] for m in alice_members] == ["alice@one.io"]
    assert [m["email"] for m in bob_members] == ["bob@two.io"]


async def test_invitations_list_never_includes_another_tenant(
    client: AsyncClient, two_tenants
) -> None:
    alice, bob = two_tenants
    await client.post(
        "/v1/console/invitations",
        json={"email": "secret@one.io", "role": "viewer"},
        headers=alice.auth,
    )

    bob_invitations = (await client.get("/v1/console/invitations", headers=bob.auth)).json()

    assert bob_invitations == []


async def test_settings_are_per_tenant(client: AsyncClient, two_tenants) -> None:
    alice, bob = two_tenants

    await client.patch(
        "/v1/console/organizations/current/settings",
        json={"threshold_preset": "strict"},
        headers=alice.auth,
    )

    bob_settings = (
        await client.get("/v1/console/organizations/current/settings", headers=bob.auth)
    ).json()

    assert bob_settings["threshold_preset"] == "balanced"
    assert float(bob_settings["match_threshold"]) == pytest.approx(0.38)


async def test_the_active_organization_comes_from_the_token_not_the_request(
    client: AsyncClient, two_tenants
) -> None:
    """No endpoint takes an organization id from the caller.

    A caller cannot address another tenant even by guessing an ID, because the
    ID is never part of the request.
    """
    alice, bob = two_tenants

    alice_org = (await client.get("/v1/console/organizations/current", headers=alice.auth)).json()
    bob_org = (await client.get("/v1/console/organizations/current", headers=bob.auth)).json()

    assert alice_org["name"] == "Tenant One"
    assert bob_org["name"] == "Tenant Two"


async def test_renaming_one_tenant_does_not_touch_the_other(
    client: AsyncClient, two_tenants
) -> None:
    alice, bob = two_tenants

    await client.patch(
        "/v1/console/organizations/current",
        json={"name": "Renamed By Alice"},
        headers=alice.auth,
    )

    bob_org = (await client.get("/v1/console/organizations/current", headers=bob.auth)).json()
    assert bob_org["name"] == "Tenant Two"


async def test_a_user_in_two_organizations_sees_only_the_active_one(
    client: AsyncClient,
) -> None:
    """Multi-org membership must not merge tenants."""
    alice = await register(client, email="alice@one.io", organization_name="Tenant One")

    second = await client.post(
        "/v1/console/organizations", json={"name": "Side Project"}, headers=alice.auth
    )
    assert second.status_code == 201

    me = (await client.get("/v1/console/auth/me", headers=alice.auth)).json()
    assert len(me["organizations"]) == 2

    # The session still points at the original organization; creating another
    # must not silently switch context.
    current = (await client.get("/v1/console/organizations/current", headers=alice.auth)).json()
    assert current["name"] == "Tenant One"


async def test_duplicate_search_never_crosses_the_tenant_boundary(
    client: AsyncClient, two_tenants
) -> None:
    """The one query that cannot use `_scoped()`.

    Duplicate detection joins templates to profiles and carries its tenant
    predicate by hand, which makes it the single place in the biometrics module
    where a forgotten filter is possible. Two tenants enrolling the *same face*
    must both succeed: leaking here would not just expose data, it would tell
    one customer that a person is enrolled with another.
    """
    alice, bob = two_tenants
    face = frames(42, 3)

    alice_subject = await create_subject(client, alice, external_id="shared_face")
    alice_response = await enroll(client, alice, alice_subject["id"], images=face)
    assert alice_response.status_code == 201, alice_response.text

    bob_subject = await create_subject(client, bob, external_id="shared_face")
    bob_response = await enroll(client, bob, bob_subject["id"], images=face)

    assert bob_response.status_code == 201, (
        "an identical face enrolled in another tenant was reported as a duplicate; "
        "the duplicate search leaked across the tenant boundary"
    )


async def test_enrollment_list_never_includes_another_tenant(
    client: AsyncClient, two_tenants
) -> None:
    alice, bob = two_tenants

    subject = await create_subject(client, alice, external_id="alice_only")
    await enroll(client, alice, subject["id"], images=frames(11, 3))

    bob_enrollments = (await client.get("/v1/console/enrollments", headers=bob.auth)).json()
    assert bob_enrollments["data"] == []
