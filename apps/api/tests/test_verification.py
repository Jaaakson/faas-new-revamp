"""Verification: decisions, thresholds, quota, and idempotency.

The properties asserted here are the ones a customer's security review asks
about:

* a rejected verification is a `200`, not an error;
* `inconclusive` is never collapsed into `rejected`, in any failure mode;
* the threshold that produced a decision is frozen onto the record, so changing
  it later cannot rewrite history;
* a per-request threshold can tighten but never loosen;
* a retried request is not charged twice.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.biometrics.models import UsageDaily, VerificationSession
from app.modules.identity.models import OrgSettings
from tests.factories import Account, create_subject, enroll, frame, frames, register


@pytest.fixture
async def owner(client: AsyncClient) -> Account:
    return await register(client, email="owner@acme.example.com", organization_name="Acme")


async def verify(
    client: AsyncClient,
    account: Account,
    subject_id: str,
    *,
    image: str | None = None,
    headers: dict[str, str] | None = None,
    **options: object,
):
    return await client.post(
        "/v1/console/verifications",
        json={
            "subject_id": subject_id,
            "image": image if image is not None else frame(1, seed=99),
            "options": options,
        },
        headers={**account.auth, **(headers or {})},
    )


@pytest.fixture
async def enrolled(client: AsyncClient, owner: Account) -> dict:
    subject = await create_subject(client, owner, external_id="user_1")
    response = await enroll(client, owner, subject["id"], images=frames(1, 3))
    assert response.status_code == 201, response.text
    return subject


# ── The core decisions ────────────────────────────────────────────────────────


async def test_the_right_face_verifies(client: AsyncClient, owner: Account, enrolled: dict) -> None:
    response = await verify(client, owner, enrolled["id"], image=frame(1, seed=77))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"] == "verified"
    assert body["similarity"] >= body["threshold"]
    assert body["confidence"] in {"high", "medium", "low"}
    assert body["failure_reason"] is None
    assert body["templates_compared"] == 3
    assert body["id"].startswith("vs_")


async def test_the_wrong_face_is_rejected_with_a_200(
    client: AsyncClient, owner: Account, enrolled: dict
) -> None:
    """ "This is not the right person" is a successful answer to the question
    asked. Returning 4xx would force every integrator to write exception
    handling around a normal business outcome.
    """
    response = await verify(client, owner, enrolled["id"], image=frame(2, seed=5))

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "rejected"
    assert body["failure_reason"] == "below_threshold"
    assert body["similarity"] < body["threshold"]
    # A rejection has no confidence band — the bands describe how much margin a
    # *verified* decision had.
    assert body["confidence"] is None


async def test_the_response_carries_a_timing_breakdown(
    client: AsyncClient, owner: Account, enrolled: dict
) -> None:
    body = (await verify(client, owner, enrolled["id"])).json()

    timing = body["timing"]
    assert timing["total_ms"] >= 0
    assert timing["detect_ms"] is not None
    assert timing["embed_ms"] is not None
    assert timing["match_ms"] is not None


async def test_a_verified_result_updates_the_subject(
    client: AsyncClient, owner: Account, enrolled: dict
) -> None:
    await verify(client, owner, enrolled["id"], image=frame(1, seed=77))

    detail = (await client.get(f"/v1/console/subjects/{enrolled['id']}", headers=owner.auth)).json()

    assert detail["verification_count"] == 1
    assert detail["last_verified_at"] is not None


# ── inconclusive is not rejected ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("image_kwargs", "expected_reason"),
    [
        ({"faces": 0}, "no_face_detected"),
        ({"faces": 2}, "multiple_faces"),
        ({"quality": 0.05}, "low_quality"),
        ({"brightness": 0.01}, "low_quality"),
    ],
)
async def test_undecidable_captures_are_inconclusive_never_rejected(
    client: AsyncClient,
    owner: Account,
    enrolled: dict,
    image_kwargs: dict,
    expected_reason: str,
) -> None:
    """Telling someone they are not who they claim, when the truth is that the
    room is too dark, is both wrong and corrupts the customer's fraud metrics
    with lighting problems.
    """
    response = await verify(client, owner, enrolled["id"], image=frame(1, **image_kwargs))

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "inconclusive", body
    assert body["failure_reason"] == expected_reason
    assert body["similarity"] is None
    assert body["guidance"], "an inconclusive result must say what to do about it"


async def test_a_subject_with_no_profile_is_inconclusive(
    client: AsyncClient, owner: Account
) -> None:
    """Not `rejected`. We have nothing to compare against, which is a different
    statement from "this is the wrong person".
    """
    subject = await create_subject(client, owner, external_id="never_enrolled")

    response = await verify(client, owner, subject["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "inconclusive"
    assert body["failure_reason"] == "subject_not_enrolled"


async def test_an_unknown_subject_is_a_404(client: AsyncClient, owner: Account) -> None:
    """A bad identifier is the caller's error, not an undecidable capture."""
    response = await verify(client, owner, "sub_01ABCDEFGHJKMNPQRSTVWXYZ00")
    assert response.status_code == 404


async def test_a_revoked_profile_makes_verification_inconclusive(
    client: AsyncClient, owner: Account, enrolled: dict
) -> None:
    await client.delete(f"/v1/console/subjects/{enrolled['id']}/face-profile", headers=owner.auth)

    body = (await verify(client, owner, enrolled["id"])).json()

    assert body["decision"] == "inconclusive"
    assert body["failure_reason"] == "subject_not_enrolled"


# ── Thresholds ────────────────────────────────────────────────────────────────


async def test_a_request_may_tighten_the_threshold(
    client: AsyncClient, owner: Account, enrolled: dict
) -> None:
    lenient = (await verify(client, owner, enrolled["id"], image=frame(1, seed=77))).json()
    assert lenient["decision"] == "verified"

    # Above any similarity the engine can produce for a genuine pair (the fake
    # engine tops out around 0.9991), so the tightening is what flips the
    # outcome rather than luck.
    strict = (
        await verify(client, owner, enrolled["id"], image=frame(1, seed=77), threshold=0.99999)
    ).json()

    assert strict["threshold"] == pytest.approx(0.99999)
    assert strict["decision"] == "rejected"
    assert strict["failure_reason"] == "below_threshold"


async def test_a_request_may_not_loosen_the_threshold(
    client: AsyncClient, owner: Account, enrolled: dict
) -> None:
    """A compromised API key must not be able to weaken the posture the
    organization configured, silently and without an audit entry.
    """
    body = (
        await verify(client, owner, enrolled["id"], image=frame(2, seed=5), threshold=0.001)
    ).json()

    # Raised to the organization default rather than honoured.
    assert body["threshold"] == pytest.approx(0.38)
    assert body["decision"] == "rejected"


async def test_the_applied_threshold_is_frozen_onto_the_record(
    client: AsyncClient, owner: Account, enrolled: dict, session: AsyncSession
) -> None:
    """An audit trail that moves is not an audit trail.

    A decision made at 0.38 must still read as 0.38 after the organization
    switches to strict — otherwise nobody can explain a past outcome.
    """
    first = (await verify(client, owner, enrolled["id"], image=frame(1, seed=77))).json()
    assert first["threshold"] == pytest.approx(0.38)

    settings_row = await session.get(OrgSettings, owner.organization_id)
    assert settings_row is not None
    settings_row.match_threshold = __import__("decimal").Decimal("0.750")
    settings_row.threshold_preset = "custom"
    await session.commit()

    later = (
        await client.get(f"/v1/console/verifications/{first['id']}", headers=owner.auth)
    ).json()
    assert later["threshold_applied"] == pytest.approx(0.38)

    fresh = (await verify(client, owner, enrolled["id"], image=frame(1, seed=77))).json()
    assert fresh["threshold"] == pytest.approx(0.75)


async def test_the_threshold_endpoint_reports_measured_error_rates(
    client: AsyncClient, owner: Account
) -> None:
    body = (await client.get("/v1/console/threshold", headers=owner.auth)).json()

    assert body["preset"] == "balanced"
    assert body["threshold"] == pytest.approx(0.38)
    assert body["far"] == pytest.approx(8e-6)
    assert body["frr"] == pytest.approx(0.0306)
    assert body["measured"] is True


async def test_a_custom_threshold_reports_no_error_rates(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    """Printing a reassuring `FAR 0.0%` for an uncalibrated configuration would
    be worse than printing nothing.
    """
    settings_row = await session.get(OrgSettings, owner.organization_id)
    assert settings_row is not None
    settings_row.match_threshold = __import__("decimal").Decimal("0.512")
    await session.commit()

    body = (await client.get("/v1/console/threshold", headers=owner.auth)).json()

    assert body["preset"] == "custom"
    assert body["far"] is None
    assert body["frr"] is None
    assert body["measured"] is False
    assert "not calibrated" in body["note"]


# ── Liveness ──────────────────────────────────────────────────────────────────


async def test_liveness_is_not_evaluated_unless_asked(
    client: AsyncClient, owner: Account, enrolled: dict
) -> None:
    """`evaluated: false` is recorded rather than inferred from a pass, so an
    auditor can see the question was never asked.
    """
    body = (await verify(client, owner, enrolled["id"], image=frame(1, seed=77))).json()
    assert body["liveness"] is None


# ── Usage and quota ───────────────────────────────────────────────────────────


async def test_each_decision_is_metered(
    client: AsyncClient, owner: Account, enrolled: dict, session: AsyncSession
) -> None:
    await verify(client, owner, enrolled["id"], image=frame(1, seed=77))
    await verify(client, owner, enrolled["id"], image=frame(2, seed=5))
    await verify(client, owner, enrolled["id"], image=frame(1, faces=0))

    row = (
        await session.execute(select(UsageDaily).where(UsageDaily.metric == "verifications"))
    ).scalar_one()

    assert row.count == 3
    assert row.success_count == 1
    assert row.rejected_count == 1
    assert row.inconclusive_count == 1


async def test_usage_is_reported_against_the_plan(
    client: AsyncClient, owner: Account, enrolled: dict
) -> None:
    await verify(client, owner, enrolled["id"])

    body = (await client.get("/v1/console/usage/current", headers=owner.auth)).json()

    assert body["plan"] == "free"
    assert body["limit"] == 1000
    assert body["used"] >= 1
    assert body["remaining"] == body["limit"] - body["used"]
    # Free hard-stops; the console needs this to say what happens at 100%.
    assert body["hard_stop"] is True


async def test_an_exhausted_quota_returns_429_with_retry_after(
    client: AsyncClient, owner: Account, enrolled: dict, session: AsyncSession
) -> None:
    """Free hard-stops at quota. The reset is a month away, so `Retry-After`
    must say so rather than inviting a retry in 60 seconds.
    """
    from datetime import UTC, datetime

    session.add(
        UsageDaily(
            organization_id=owner.organization_id,
            day=datetime.now(tz=UTC).strftime("%Y-%m-%d"),
            metric="verifications",
            count=1000,
        )
    )
    await session.commit()

    response = await verify(client, owner, enrolled["id"])

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["Retry-After"]) > 3600


async def test_an_exhausted_quota_does_not_block_a_paid_plan(
    client: AsyncClient, owner: Account, enrolled: dict, session: AsyncSession
) -> None:
    """Breaking a paying customer's login flow over a billing event would be a
    far worse failure than an unexpected invoice line.
    """
    from datetime import UTC, datetime

    from app.modules.identity.models import Organization

    organization = await session.get(Organization, owner.organization_id)
    assert organization is not None
    organization.plan = "growth"
    session.add(
        UsageDaily(
            organization_id=owner.organization_id,
            day=datetime.now(tz=UTC).strftime("%Y-%m-%d"),
            metric="verifications",
            count=999_999,
        )
    )
    await session.commit()

    response = await verify(client, owner, enrolled["id"])

    assert response.status_code == 200


# ── Idempotency ───────────────────────────────────────────────────────────────


async def test_a_repeated_idempotency_key_replays_without_recomputing(
    client: AsyncClient, owner: Account, enrolled: dict, session: AsyncSession
) -> None:
    headers = {"Idempotency-Key": "idem_test_replay_1"}

    first = await verify(client, owner, enrolled["id"], image=frame(1, seed=77), headers=headers)
    second = await verify(client, owner, enrolled["id"], image=frame(1, seed=77), headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.headers.get("Idempotent-Replay") == "true"

    sessions = await session.scalar(select(func.count()).select_from(VerificationSession))
    assert sessions == 1, "the replayed request created a second session"


async def test_a_replayed_request_is_not_charged_twice(
    client: AsyncClient, owner: Account, enrolled: dict, session: AsyncSession
) -> None:
    headers = {"Idempotency-Key": "idem_test_quota_1"}

    await verify(client, owner, enrolled["id"], headers=headers)
    await verify(client, owner, enrolled["id"], headers=headers)
    await verify(client, owner, enrolled["id"], headers=headers)

    used = await session.scalar(
        select(func.coalesce(func.sum(UsageDaily.count), 0)).where(
            UsageDaily.metric == "verifications"
        )
    )
    assert used == 1


async def test_different_keys_are_separate_requests(
    client: AsyncClient, owner: Account, enrolled: dict, session: AsyncSession
) -> None:
    await verify(client, owner, enrolled["id"], headers={"Idempotency-Key": "a"})
    await verify(client, owner, enrolled["id"], headers={"Idempotency-Key": "b"})

    sessions = await session.scalar(select(func.count()).select_from(VerificationSession))
    assert sessions == 2


# ── Listing and detail ────────────────────────────────────────────────────────


async def test_the_list_resolves_the_subject_external_id(
    client: AsyncClient, owner: Account, enrolled: dict
) -> None:
    await verify(client, owner, enrolled["id"])

    body = (await client.get("/v1/console/verifications", headers=owner.auth)).json()

    assert len(body["data"]) == 1
    assert body["data"][0]["subject_external_id"] == "user_1"


async def test_the_list_can_be_filtered_by_decision(
    client: AsyncClient, owner: Account, enrolled: dict
) -> None:
    await verify(client, owner, enrolled["id"], image=frame(1, seed=77))
    await verify(client, owner, enrolled["id"], image=frame(2, seed=5))

    rejected = (
        await client.get("/v1/console/verifications?decision=rejected", headers=owner.auth)
    ).json()

    assert len(rejected["data"]) == 1
    assert rejected["data"][0]["decision"] == "rejected"


async def test_detail_includes_the_quality_evidence(
    client: AsyncClient, owner: Account, enrolled: dict
) -> None:
    created = (await verify(client, owner, enrolled["id"], image=frame(1, seed=77))).json()

    body = (
        await client.get(f"/v1/console/verifications/{created['id']}", headers=owner.auth)
    ).json()

    assert body["id"] == created["id"]
    assert body["templates_compared"] == 3
    assert body["quality"] is not None
    assert body["quality"]["face_size_px"] > 0
    assert body["quality"]["pose"]["yaw"] == pytest.approx(0.0)


# ── Authorization ─────────────────────────────────────────────────────────────


async def test_a_viewer_cannot_verify(client: AsyncClient, owner: Account, enrolled: dict) -> None:
    from tests.factories import invite_and_join

    viewer = await invite_and_join(
        client, inviter=owner, email="viewer@acme.example.com", role="viewer"
    )

    response = await verify(client, viewer, enrolled["id"])

    assert response.status_code == 403


async def test_an_unauthenticated_request_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/console/verifications", json={"subject_id": "sub_x", "image": frame(1)}
    )
    assert response.status_code == 401
