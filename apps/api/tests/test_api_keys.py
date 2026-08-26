"""API keys and the public `/v1` surface.

The properties asserted here are the ones that decide whether a stolen key is a
contained incident or a breach:

* the secret is returned once and is not recoverable from the database;
* revocation takes effect on the *next* request, not when a cache expires;
* a key cannot mint another key, or reach settings, members or billing;
* scopes narrow what a key can do, and cannot widen beyond its creator's role;
* another tenant's key is indistinguishable from a nonexistent one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity import api_keys as service
from app.modules.identity.models import ApiKey
from tests.factories import (
    Account,
    create_subject,
    frame,
    frames,
    invite_and_join,
    mark_email_verified,
    register,
)


@pytest.fixture
async def owner(client: AsyncClient, session: AsyncSession) -> Account:
    """A verified owner.

    Key creation requires a verified email on purpose: a key whose owner we
    cannot reach is a key nobody can be told to revoke.
    """
    account = await register(client, email="owner@acme.example.com", organization_name="Acme")
    await mark_email_verified(session, account)
    return account


async def make_key(client: AsyncClient, account: Account, **body: object) -> dict:
    payload = {"name": "Test key", "environment": "test", **body}
    response = await client.post("/v1/console/api-keys", json=payload, headers=account.auth)
    assert response.status_code == 201, response.text
    return response.json()


def key_auth(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


# ── Minting ───────────────────────────────────────────────────────────────────


def test_a_secret_has_the_documented_shape() -> None:
    secret, prefix, digest, last4 = service.generate_secret("live")

    assert secret.startswith("fvas_live_")
    assert len(secret) == len("fvas_live_") + service.SECRET_LENGTH
    assert prefix == secret[: len("fvas_live_") + service.PREFIX_SECRET_CHARS]
    assert secret.endswith(last4)
    assert len(digest) == 64


def test_every_secret_parses_back_to_its_own_prefix() -> None:
    """The regression that made 45% of keys unusable.

    `secrets.token_urlsafe` includes `_` in its alphabet, so a naive
    `secret.split("_")` produced four parts and rejected the key as malformed.
    Minting one and immediately failing to authenticate with it is exactly how
    this surfaced, so the property is asserted directly here too.
    """
    for _ in range(300):
        secret, prefix, _digest, _last4 = service.generate_secret("test")
        assert service.parse_prefix(secret) == prefix, secret


def test_two_secrets_are_never_the_same() -> None:
    secrets = {service.generate_secret("test")[0] for _ in range(200)}
    assert len(secrets) == 200


@pytest.mark.parametrize(
    "malformed",
    ["", "nope", "fvas_live", "fvas_prod_abcdefgh", "fvas_live_short", "Bearer fvas_live_x"],
)
def test_a_malformed_secret_is_rejected_before_the_database(malformed: str) -> None:
    """Shape is checked first, so garbage never becomes a query."""
    assert service.parse_prefix(malformed) is None


# ── Reveal-once ───────────────────────────────────────────────────────────────


async def test_the_secret_is_returned_once_and_never_stored(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    created = await make_key(client, owner)
    secret = created["secret"]

    listed = (await client.get("/v1/console/api-keys", headers=owner.auth)).json()
    assert "secret" not in listed[0]

    # And nothing in the row can reconstruct it.
    row = (await session.execute(select(ApiKey))).scalar_one()
    assert secret not in (row.key_hash, row.key_prefix, row.last4)
    assert row.key_hash == service.hash_secret(secret)
    assert len(row.key_hash) == 64


async def test_creating_a_key_writes_an_audit_entry_without_the_secret(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    """An audit log containing a working credential is a credential store."""
    created = await make_key(client, owner)

    from app.modules.biometrics.models import AuditLog

    entry = (
        await session.execute(select(AuditLog).where(AuditLog.action == "apikey.created"))
    ).scalar_one()

    assert entry.changes is not None
    assert created["secret"] not in str(entry.changes)
    assert entry.changes["prefix"] == created["key_prefix"]


# ── The public surface ────────────────────────────────────────────────────────


async def test_a_key_can_drive_the_whole_loop(client: AsyncClient, owner: Account) -> None:
    """Create, enroll, verify — using only an API key, no JWT anywhere."""
    key = await make_key(client, owner)
    auth = key_auth(key["secret"])

    created = await client.post("/v1/subjects", json={"external_id": "api_user_1"}, headers=auth)
    assert created.status_code == 201, created.text
    subject_id = created.json()["id"]

    enrolled = await client.post(
        "/v1/enrollments",
        json={"subject_id": subject_id, "images": frames(1, 3)},
        headers=auth,
    )
    assert enrolled.status_code == 201, enrolled.text
    assert enrolled.json()["face_profile"]["template_count"] == 3

    verified = await client.post(
        "/v1/verifications",
        json={"subject_id": subject_id, "image": frame(1, seed=77)},
        headers=auth,
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["decision"] == "verified"


async def test_the_public_path_produces_the_same_result_as_the_console(
    client: AsyncClient, owner: Account
) -> None:
    """Both planes call one service, so this is a check that the wiring did not
    accidentally introduce a second code path.
    """
    key = await make_key(client, owner)
    auth = key_auth(key["secret"])

    console_subject = await create_subject(client, owner, external_id="via_console")
    api_subject = (
        await client.post("/v1/subjects", json={"external_id": "via_api"}, headers=auth)
    ).json()

    from tests.factories import enroll

    console_enrolled = await enroll(client, owner, console_subject["id"], images=frames(4, 3))
    api_enrolled = await client.post(
        "/v1/enrollments",
        json={"subject_id": api_subject["id"], "images": frames(5, 3)},
        headers=auth,
    )

    left = console_enrolled.json()["face_profile"]
    right = api_enrolled.json()["face_profile"]

    assert left["version"] == right["version"] == 1
    assert left["template_count"] == right["template_count"] == 3
    assert left["model"] == right["model"]
    assert left["status"] == right["status"] == "active"


async def test_an_api_action_is_attributed_to_the_key_not_a_person(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    """The key's creator must not appear to have taken an action months later
    that their key took.
    """
    key = await make_key(client, owner)
    await client.post(
        "/v1/subjects", json={"external_id": "attribution"}, headers=key_auth(key["secret"])
    )

    from app.modules.biometrics.models import AuditLog

    entry = (
        await session.execute(select(AuditLog).where(AuditLog.action == "subject.created"))
    ).scalar_one()

    assert entry.actor_type == "api_key"
    assert entry.actor_id is None
    assert entry.actor_email == f"key:{key['key_prefix']}"


# ── Rejection ─────────────────────────────────────────────────────────────────


async def test_no_key_is_a_401(client: AsyncClient) -> None:
    response = await client.post("/v1/subjects", json={"external_id": "x"})
    assert response.status_code == 401


async def test_a_wrong_secret_is_a_401(client: AsyncClient, owner: Account) -> None:
    await make_key(client, owner)
    forged = f"fvas_test_{'a' * service.SECRET_LENGTH}"

    response = await client.post(
        "/v1/subjects", json={"external_id": "x"}, headers=key_auth(forged)
    )
    assert response.status_code == 401


async def test_rejection_never_says_why(client: AsyncClient, owner: Account) -> None:
    """Distinguishing "no such key" from "revoked" tells an attacker which of
    their guesses was a real key.
    """
    key = await make_key(client, owner)
    await client.delete(f"/v1/console/api-keys/{key['id']}", headers=owner.auth)

    revoked = await client.post(
        "/v1/subjects", json={"external_id": "x"}, headers=key_auth(key["secret"])
    )
    unknown = await client.post(
        "/v1/subjects",
        json={"external_id": "x"},
        headers=key_auth(f"fvas_test_{'z' * service.SECRET_LENGTH}"),
    )

    assert revoked.status_code == unknown.status_code == 401
    assert revoked.json()["error"]["message"] == unknown.json()["error"]["message"]


async def test_revocation_takes_effect_on_the_next_request(
    client: AsyncClient, owner: Account
) -> None:
    """No cache, no grace period. This is the property that makes revocation a
    real control rather than a suggestion.
    """
    key = await make_key(client, owner)
    auth = key_auth(key["secret"])

    before = await client.post("/v1/subjects", json={"external_id": "before"}, headers=auth)
    assert before.status_code == 201

    await client.delete(f"/v1/console/api-keys/{key['id']}", headers=owner.auth)

    after = await client.post("/v1/subjects", json={"external_id": "after"}, headers=auth)
    assert after.status_code == 401


async def test_an_expired_key_stops_working(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    key = await make_key(client, owner)
    row = await session.get(ApiKey, key["id"])
    assert row is not None
    row.expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
    await session.commit()

    response = await client.post(
        "/v1/subjects", json={"external_id": "x"}, headers=key_auth(key["secret"])
    )
    assert response.status_code == 401


# ── Scopes ────────────────────────────────────────────────────────────────────


async def test_a_key_only_does_what_it_was_scoped_for(client: AsyncClient, owner: Account) -> None:
    key = await make_key(client, owner, scopes=["verification:write", "subject:read"])
    auth = key_auth(key["secret"])

    assert key["scopes"] == ["subject:read", "verification:write"]

    created = await client.post("/v1/subjects", json={"external_id": "x"}, headers=auth)
    assert created.status_code == 403
    assert created.json()["error"]["details"]["required_scope"] == "subject:write"


async def test_a_key_cannot_be_granted_a_console_only_permission(
    client: AsyncClient, owner: Account
) -> None:
    """A key that could read the audit log or change settings would defeat the
    point of separating the two planes.
    """
    response = await client.post(
        "/v1/console/api-keys",
        json={"name": "sneaky", "environment": "test", "scopes": ["settings:update"]},
        headers=owner.auth,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_scopes"


async def test_a_key_cannot_exceed_its_creators_role(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    """A Developer cannot delete subjects, so a key they mint cannot either —
    otherwise a key is a way around RBAC.
    """
    developer = await invite_and_join(
        client, inviter=owner, email="dev@acme.example.com", role="developer"
    )
    await mark_email_verified(session, developer)

    response = await client.post(
        "/v1/console/api-keys",
        json={"name": "dev key", "environment": "test", "scopes": ["subject:delete"]},
        headers=developer.auth,
    )

    assert response.status_code == 400, response.text


async def test_a_key_cannot_reach_the_console_plane(client: AsyncClient, owner: Account) -> None:
    """Even with every grantable scope, a key is not a console session."""
    key = await make_key(client, owner)
    auth = key_auth(key["secret"])

    for path in (
        "/v1/console/api-keys",
        "/v1/console/members",
        "/v1/console/organizations/current/settings",
        "/v1/console/logs/audit",
    ):
        response = await client.get(path, headers=auth)
        assert response.status_code == 401, f"{path} accepted an API key"


async def test_a_key_cannot_mint_another_key(client: AsyncClient, owner: Account) -> None:
    """If a stolen key could mint more, revoking the stolen one would not end
    the compromise.
    """
    key = await make_key(client, owner)

    response = await client.post(
        "/v1/console/api-keys",
        json={"name": "child", "environment": "live"},
        headers=key_auth(key["secret"]),
    )
    assert response.status_code == 401


# ── Rotation ──────────────────────────────────────────────────────────────────


async def test_rotation_keeps_both_keys_working(client: AsyncClient, owner: Account) -> None:
    """The overlap is what lets a customer redeploy without a window of 401s."""
    old = await make_key(client, owner)

    rotated = await client.post(f"/v1/console/api-keys/{old['id']}/rotate", headers=owner.auth)
    assert rotated.status_code == 201
    new = rotated.json()

    assert new["secret"] != old["secret"]
    assert new["scopes"] == old["scopes"]

    for secret in (old["secret"], new["secret"]):
        response = await client.post(
            "/v1/subjects",
            json={"external_id": f"user_{secret[-4:]}"},
            headers=key_auth(secret),
        )
        assert response.status_code == 201, f"{secret[:14]}… stopped working during rotation"


async def test_the_old_key_stops_working_once_the_overlap_elapses(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    old = await make_key(client, owner)
    await client.post(f"/v1/console/api-keys/{old['id']}/rotate", headers=owner.auth)

    row = await session.get(ApiKey, old["id"])
    assert row is not None
    row.rotated_at = datetime.now(tz=UTC) - service.ROTATION_OVERLAP - timedelta(seconds=1)
    await session.commit()

    response = await client.post(
        "/v1/subjects", json={"external_id": "late"}, headers=key_auth(old["secret"])
    )
    assert response.status_code == 401


# ── Tenancy ───────────────────────────────────────────────────────────────────


async def test_a_key_only_sees_its_own_tenant(client: AsyncClient, owner: Account) -> None:
    other = await register(client, email="bob@other.example.com", organization_name="Other")
    other_subject = await create_subject(client, other, external_id="theirs")

    key = await make_key(client, owner)
    response = await client.get(
        f"/v1/subjects/{other_subject['id']}", headers=key_auth(key["secret"])
    )

    assert response.status_code == 404


async def test_another_tenants_key_cannot_be_revoked(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    other = await register(client, email="bob@other.example.com", organization_name="Other")
    await mark_email_verified(session, other)
    theirs = await make_key(client, other)

    response = await client.delete(f"/v1/console/api-keys/{theirs['id']}", headers=owner.auth)

    assert response.status_code == 404


async def test_the_key_list_never_includes_another_tenant(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    other = await register(client, email="bob@other.example.com", organization_name="Other")
    await mark_email_verified(session, other)
    await make_key(client, other)
    await make_key(client, owner)

    listed = (await client.get("/v1/console/api-keys", headers=owner.auth)).json()
    assert len(listed) == 1


# ── IP allowlist ──────────────────────────────────────────────────────────────


def _key(**overrides: object) -> ApiKey:
    defaults = {
        "organization_id": "org_1",
        "name": "k",
        "environment": "live",
        "key_prefix": "fvas_live_aaaaaaaa",
        "key_hash": "0" * 64,
        "last4": "abcd",
        "scopes": [],
    }
    return ApiKey(**{**defaults, **overrides})


def test_an_unset_allowlist_allows_everything() -> None:
    """Opt-in. Defaulting to deny would lock out every existing integration the
    moment the column was added.
    """
    assert service.ip_is_allowed(_key(ip_allowlist=None), "203.0.113.9") is True


def test_an_allowlist_admits_matching_addresses_only() -> None:
    key = _key(ip_allowlist="203.0.113.0/24, 198.51.100.7/32")

    assert service.ip_is_allowed(key, "203.0.113.9") is True
    assert service.ip_is_allowed(key, "198.51.100.7") is True
    assert service.ip_is_allowed(key, "192.0.2.1") is False


def test_an_allowlisted_key_denies_an_unidentifiable_caller() -> None:
    """Failing open here would make the control bypassable behind any proxy
    that strips the client address.
    """
    assert service.ip_is_allowed(_key(ip_allowlist="203.0.113.0/24"), None) is False


def test_a_malformed_allowlist_entry_is_ignored_not_fatal() -> None:
    """One bad row must not lock a customer out of their own API."""
    key = _key(ip_allowlist="not-a-cidr, 203.0.113.0/24")
    assert service.ip_is_allowed(key, "203.0.113.9") is True


def test_a_test_key_never_carries_an_allowlist() -> None:
    """A test key is used from a laptop on a changing address; silently
    applying a restriction would look like the key is broken.
    """
    minted = service.mint(
        organization_id="org_1",
        name="k",
        environment="test",
        scopes=[],
        created_by_user_id=None,
        ip_allowlist="203.0.113.0/24",
    )
    assert minted.api_key.ip_allowlist is None
