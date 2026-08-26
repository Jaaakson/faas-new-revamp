"""End-to-end authentication behaviour."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import AuthEvent, AuthLog, RefreshToken
from app.modules.identity.models import Membership, Organization, User
from tests.factories import DEFAULT_PASSWORD, login, register

REGISTER = "/v1/console/auth/register"
LOGIN = "/v1/console/auth/login"
REFRESH = "/v1/console/auth/refresh"
LOGOUT = "/v1/console/auth/logout"
ME = "/v1/console/auth/me"


# ── Registration ──────────────────────────────────────────────────────────────


async def test_registration_creates_owner_of_a_personal_organization(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(client, email="rani@acme.io", full_name="Rani Wulandari")

    assert account.organization_id is not None

    membership = await session.scalar(
        select(Membership).where(Membership.user_id == account.user_id)
    )
    assert membership is not None
    assert membership.role.slug == "owner"
    assert membership.status == "active"


async def test_registration_returns_a_usable_session(client: AsyncClient) -> None:
    """The user lands signed in rather than bounced to a login form."""
    account = await register(client, email="rani@acme.io")

    response = await client.get(ME, headers=account.auth)

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "rani@acme.io"


async def test_email_is_normalised_to_lowercase(client: AsyncClient, session: AsyncSession) -> None:
    """Explicit normalisation is what makes the unique index actually unique."""
    await register(client, email="Rani@Acme.IO")

    user = await session.scalar(select(User).where(User.email == "rani@acme.io"))
    assert user is not None

    # The same address in different case must not create a second account.
    duplicate = await client.post(
        REGISTER,
        json={"email": "RANI@ACME.IO", "password": DEFAULT_PASSWORD, "full_name": "Impostor"},
    )
    assert duplicate.status_code == 409


async def test_duplicate_email_is_rejected(client: AsyncClient) -> None:
    await register(client, email="rani@acme.io")

    response = await client.post(
        REGISTER,
        json={"email": "rani@acme.io", "password": DEFAULT_PASSWORD, "full_name": "Other"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("short", "too short"),
        ("password123", "common"),
        ("aaaaaaaaaaaa", "common"),
    ],
)
async def test_weak_passwords_are_rejected(client: AsyncClient, password: str, reason: str) -> None:
    response = await client.post(
        REGISTER,
        json={"email": "weak@acme.io", "password": password, "full_name": "Weak"},
    )

    assert response.status_code in {400, 422}, f"expected rejection for {reason}"


async def test_email_starts_unverified(client: AsyncClient) -> None:
    """Verification gates key creation later; it must not be granted for free."""
    account = await register(client, email="rani@acme.io")

    body = (await client.get(ME, headers=account.auth)).json()
    assert body["user"]["email_verified"] is False


# ── Login ─────────────────────────────────────────────────────────────────────


async def test_login_succeeds_with_correct_credentials(client: AsyncClient) -> None:
    await register(client, email="rani@acme.io")
    account = await login(client, email="rani@acme.io")

    assert account.access_token
    assert account.refresh_token
    assert account.organization_id is not None


async def test_login_rejects_a_wrong_password(client: AsyncClient) -> None:
    await register(client, email="rani@acme.io")

    response = await client.post(
        LOGIN, json={"email": "rani@acme.io", "password": "wrong-password-entirely"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_login_gives_the_same_error_for_an_unknown_account(
    client: AsyncClient,
) -> None:
    """A different status or message here is an account-enumeration oracle."""
    await register(client, email="rani@acme.io")

    wrong_password = await client.post(
        LOGIN, json={"email": "rani@acme.io", "password": "wrong-password-entirely"}
    )
    unknown_account = await client.post(
        LOGIN, json={"email": "nobody@acme.io", "password": "wrong-password-entirely"}
    )

    assert wrong_password.status_code == unknown_account.status_code
    assert wrong_password.json()["error"]["message"] == (unknown_account.json()["error"]["message"])


async def test_repeated_failures_lock_the_account(
    client: AsyncClient, session: AsyncSession
) -> None:
    await register(client, email="rani@acme.io")

    for _ in range(5):
        await client.post(
            LOGIN, json={"email": "rani@acme.io", "password": "wrong-password-entirely"}
        )

    # Even the correct password is refused while locked.
    response = await client.post(
        LOGIN, json={"email": "rani@acme.io", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_locked"

    locked = await session.scalar(select(AuthLog).where(AuthLog.event == AuthEvent.LOGIN_LOCKED))
    assert locked is not None


async def test_successful_login_clears_failed_attempts(
    client: AsyncClient, session: AsyncSession
) -> None:
    await register(client, email="rani@acme.io")

    for _ in range(3):
        await client.post(
            LOGIN, json={"email": "rani@acme.io", "password": "wrong-password-entirely"}
        )
    await login(client, email="rani@acme.io")

    user = await session.scalar(select(User).where(User.email == "rani@acme.io"))
    await session.refresh(user)  # type: ignore[arg-type]
    assert user is not None
    assert user.failed_login_count == 0
    assert user.locked_until is None


# ── Refresh rotation and reuse detection ──────────────────────────────────────


async def test_refresh_rotates_the_token(client: AsyncClient) -> None:
    account = await register(client, email="rani@acme.io")

    response = await client.post(REFRESH, json={"refresh_token": account.refresh_token})

    assert response.status_code == 200
    assert response.json()["refresh_token"] != account.refresh_token


async def test_the_old_refresh_token_stops_working(client: AsyncClient) -> None:
    account = await register(client, email="rani@acme.io")
    await client.post(REFRESH, json={"refresh_token": account.refresh_token})

    replay = await client.post(REFRESH, json={"refresh_token": account.refresh_token})

    assert replay.status_code == 401


async def test_reuse_revokes_the_whole_family(client: AsyncClient, session: AsyncSession) -> None:
    """The property that turns a stolen token into a detected incident.

    Replaying a rotated token means it leaked. Revoking only that token would
    leave the thief's newer token working; revoking the family ends both
    sessions and forces re-authentication.
    """
    account = await register(client, email="rani@acme.io")
    rotated = (await client.post(REFRESH, json={"refresh_token": account.refresh_token})).json()[
        "refresh_token"
    ]

    # Replay the superseded token.
    replay = await client.post(REFRESH, json={"refresh_token": account.refresh_token})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "token_reuse_detected"

    # The token the attacker would be holding is now dead too.
    after = await client.post(REFRESH, json={"refresh_token": rotated})
    assert after.status_code == 401

    event = await session.scalar(
        select(AuthLog).where(AuthLog.event == AuthEvent.TOKEN_REUSE_DETECTED)
    )
    assert event is not None, "reuse must be recorded, not silently handled"
    assert event.success is False


async def test_refresh_tokens_are_not_stored_in_plaintext(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await register(client, email="rani@acme.io")

    stored = list(await session.scalars(select(RefreshToken)))

    assert stored
    assert all(row.token_hash != account.refresh_token for row in stored)
    assert all(len(row.token_hash) == 64 for row in stored)


async def test_logout_revokes_the_session(client: AsyncClient) -> None:
    account = await register(client, email="rani@acme.io")

    await client.post(LOGOUT, json={"refresh_token": account.refresh_token}, headers=account.auth)
    response = await client.post(REFRESH, json={"refresh_token": account.refresh_token})

    assert response.status_code == 401


# ── Password reset ────────────────────────────────────────────────────────────


async def test_forgot_password_does_not_disclose_account_existence(
    client: AsyncClient,
) -> None:
    await register(client, email="rani@acme.io")

    known = await client.post("/v1/console/auth/forgot-password", json={"email": "rani@acme.io"})
    unknown = await client.post(
        "/v1/console/auth/forgot-password", json={"email": "nobody@acme.io"}
    )

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


async def test_reset_password_revokes_every_session(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A reset is the remedy for a compromise, so it must end the attacker's session."""
    from datetime import UTC, datetime, timedelta

    from app.core.security import generate_token, hash_token
    from app.modules.auth.models import PasswordResetToken

    account = await register(client, email="rani@acme.io")

    raw = generate_token()
    session.add(
        PasswordResetToken(
            user_id=account.user_id,
            token_hash=hash_token(raw),
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=30),
        )
    )
    await session.commit()

    reset = await client.post(
        "/v1/console/auth/reset-password",
        json={"token": raw, "password": "a-completely-new-passphrase"},
    )
    assert reset.status_code == 200

    stale = await client.post(REFRESH, json={"refresh_token": account.refresh_token})
    assert stale.status_code == 401

    await login(client, email="rani@acme.io", password="a-completely-new-passphrase")


async def test_a_reset_token_is_single_use(client: AsyncClient, session: AsyncSession) -> None:
    from datetime import UTC, datetime, timedelta

    from app.core.security import generate_token, hash_token
    from app.modules.auth.models import PasswordResetToken

    account = await register(client, email="rani@acme.io")
    raw = generate_token()
    session.add(
        PasswordResetToken(
            user_id=account.user_id,
            token_hash=hash_token(raw),
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=30),
        )
    )
    await session.commit()

    first = await client.post(
        "/v1/console/auth/reset-password",
        json={"token": raw, "password": "a-completely-new-passphrase"},
    )
    second = await client.post(
        "/v1/console/auth/reset-password",
        json={"token": raw, "password": "another-different-passphrase"},
    )

    assert first.status_code == 200
    assert second.status_code == 400


# ── Tokens and access control basics ──────────────────────────────────────────


async def test_protected_route_requires_a_token(client: AsyncClient) -> None:
    response = await client.get(ME)
    assert response.status_code == 401


async def test_a_garbage_token_is_rejected(client: AsyncClient) -> None:
    response = await client.get(ME, headers={"Authorization": "Bearer not-a-real-jwt"})
    assert response.status_code == 401


async def test_a_token_signed_with_another_key_is_rejected(client: AsyncClient) -> None:
    import jwt

    forged = jwt.encode(
        {"sub": "usr_fake", "type": "access", "exp": 9999999999, "iat": 0},
        "an-attacker-chosen-secret",
        algorithm="HS256",
    )

    response = await client.get(ME, headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


async def test_me_reports_organizations_and_permissions(client: AsyncClient) -> None:
    account = await register(client, email="rani@acme.io", organization_name="Acme Corp")

    body = (await client.get(ME, headers=account.auth)).json()

    assert len(body["organizations"]) == 1
    assert body["organizations"][0]["name"] == "Acme Corp"
    assert body["organizations"][0]["role"] == "owner"
    # Owner holds every permission by definition.
    assert "billing:manage" in body["permissions"]
    assert "threshold:update" in body["permissions"]


async def test_organization_slug_collisions_are_resolved(
    client: AsyncClient, session: AsyncSession
) -> None:
    await register(client, email="one@acme.io", organization_name="Acme Corp")
    await register(client, email="two@acme.io", organization_name="Acme Corp")

    slugs = list(await session.scalars(select(Organization.slug)))
    assert len(slugs) == len(set(slugs)), "slugs must stay unique"
