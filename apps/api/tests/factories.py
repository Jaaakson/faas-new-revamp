"""Test helpers for building authenticated users and organizations.

Keeps the intent of each test visible: a test about the last-Owner invariant
should read as one, not as fifteen lines of fixture assembly.
"""

from __future__ import annotations

from dataclasses import dataclass

from httpx import AsyncClient

DEFAULT_PASSWORD = "correct-horse-battery-staple"


@dataclass
class Account:
    """A registered user with an active session."""

    email: str
    password: str
    user_id: str
    organization_id: str | None
    access_token: str
    refresh_token: str

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


async def register(
    client: AsyncClient,
    *,
    email: str,
    password: str = DEFAULT_PASSWORD,
    full_name: str = "Test User",
    organization_name: str | None = None,
    invitation_token: str | None = None,
) -> Account:
    payload: dict[str, object] = {
        "email": email,
        "password": password,
        "full_name": full_name,
    }
    if organization_name:
        payload["organization_name"] = organization_name
    if invitation_token:
        payload["invitation_token"] = invitation_token

    response = await client.post("/v1/console/auth/register", json=payload)
    assert response.status_code == 201, response.text

    body = response.json()
    organization = body.get("organization")
    return Account(
        email=email,
        password=password,
        user_id=body["user"]["id"],
        organization_id=organization["id"] if organization else None,
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
    )


async def login(client: AsyncClient, *, email: str, password: str = DEFAULT_PASSWORD) -> Account:
    response = await client.post(
        "/v1/console/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    organization = body.get("organization")
    return Account(
        email=email,
        password=password,
        user_id=body["user"]["id"],
        organization_id=organization["id"] if organization else None,
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
    )


async def invite_and_join(
    client: AsyncClient,
    *,
    inviter: Account,
    email: str,
    role: str,
    full_name: str = "Invited User",
) -> Account:
    """Invite someone and register them through the invitation.

    Produces a member of the inviter's organization holding `role` — the setup
    every RBAC test needs.
    """
    response = await client.post(
        "/v1/console/invitations",
        json={"email": email, "role": role},
        headers=inviter.auth,
    )
    assert response.status_code == 201, response.text
    token = response.json()["token"]

    return await register(
        client,
        email=email,
        full_name=full_name,
        invitation_token=token,
    )


# ── Biometrics ────────────────────────────────────────────────────────────────


def frame(
    identity: int = 1,
    *,
    quality: float = 0.9,
    brightness: float = 0.5,
    yaw: float = 0.0,
    pitch: float = 0.0,
    roll: float = 0.0,
    faces: int = 1,
    seed: int = 0,
) -> str:
    """A base64 frame the fake engine interprets as described.

    `seed` perturbs the bytes without changing the intent, which is how a test
    gets several *different captures of the same person*: same identity, same
    quality, slightly different embedding.
    """
    import base64

    from app.modules.biometrics.engine.fake import synthetic_image

    payload = bytearray(
        synthetic_image(
            identity,
            quality=quality,
            brightness=brightness,
            yaw=yaw,
            pitch=pitch,
            roll=roll,
            faces=faces,
        )
    )
    if seed:
        # Past the header, so the engine still reads the same instructions.
        payload[-4:] = seed.to_bytes(4, "little")
    return base64.b64encode(bytes(payload)).decode()


def frames(identity: int = 1, count: int = 3, **kwargs: object) -> list[str]:
    """`count` distinct captures of one person."""
    return [frame(identity, seed=index + 1, **kwargs) for index in range(count)]  # type: ignore[arg-type]


async def create_subject(
    client: AsyncClient,
    account: Account,
    *,
    external_id: str = "user_1",
    display_name: str | None = "Test Subject",
) -> dict:
    response = await client.post(
        "/v1/console/subjects",
        json={"external_id": external_id, "display_name": display_name},
        headers=account.auth,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def enroll(
    client: AsyncClient,
    account: Account,
    subject_id: str,
    *,
    images: list[str] | None = None,
    **options: object,
):
    return await client.post(
        "/v1/console/enrollments",
        json={
            "subject_id": subject_id,
            "images": images if images is not None else frames(1, 3),
            "options": options,
        },
        headers=account.auth,
    )


async def mark_email_verified(session, account: Account) -> None:
    """Simulate the user clicking the verification link.

    The register endpoint issues the token but does not return it — it is
    emailed, and there is no mail server in the suite. Flipping the column
    directly is the honest stand-in: it reproduces the *state* the link
    produces, without pretending to test the link itself.
    """
    from datetime import UTC, datetime

    from app.modules.identity.models import User

    user = await session.get(User, account.user_id)
    assert user is not None
    user.email_verified_at = datetime.now(tz=UTC)
    await session.commit()
