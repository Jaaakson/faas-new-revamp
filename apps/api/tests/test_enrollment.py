"""Enrollment, profile versioning, duplicate detection, and deletion.

End-to-end through the real HTTP surface. What is asserted here is behaviour a
customer or a regulator would care about, not implementation:

* a failed enrollment still leaves a diagnostic record,
* re-enrolling supersedes rather than overwrites,
* the same face under two identities is a surfaced decision, never a silent
  success,
* deletion physically destroys templates, and raw frames are never stored.

The last two are compliance claims. They are checked against the database, not
against the API response — an endpoint that reports success proves nothing about
what is on disk.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.biometrics.models import (
    AuditLog,
    EnrollmentAttempt,
    FaceProfile,
    FaceTemplate,
    Subject,
)
from app.modules.identity.models import OrgSettings
from tests.factories import (
    Account,
    create_subject,
    enroll,
    frame,
    frames,
    invite_and_join,
    register,
)


@pytest.fixture
async def owner(client: AsyncClient) -> Account:
    return await register(client, email="owner@acme.example.com", organization_name="Acme")


# ── Subjects ──────────────────────────────────────────────────────────────────


async def test_a_new_subject_is_pending_until_a_face_is_enrolled(
    client: AsyncClient, owner: Account
) -> None:
    """A subject is not an identity until it has biometrics."""
    subject = await create_subject(client, owner, external_id="user_84213")

    assert subject["status"] == "pending"
    assert subject["enrolled_at"] is None
    assert subject["id"].startswith("sub_")


async def test_a_duplicate_external_id_is_rejected(client: AsyncClient, owner: Account) -> None:
    await create_subject(client, owner, external_id="user_1")

    response = await client.post(
        "/v1/console/subjects",
        json={"external_id": "user_1"},
        headers=owner.auth,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "subject_already_exists"


async def test_a_subject_can_be_addressed_by_the_customers_own_identifier(
    client: AsyncClient, owner: Account
) -> None:
    """`ext_` saves integrators a lookup round trip on every call."""
    created = await create_subject(client, owner, external_id="user_84213")

    response = await client.get("/v1/console/subjects/ext_user_84213", headers=owner.auth)

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_an_unknown_external_id_is_a_404_not_a_crash(
    client: AsyncClient, owner: Account
) -> None:
    response = await client.get("/v1/console/subjects/ext_nobody", headers=owner.auth)
    assert response.status_code == 404


async def test_status_cannot_be_set_to_enrolled_by_hand(
    client: AsyncClient, owner: Account
) -> None:
    """`enrolled` is a statement about whether biometric data exists. Only the
    enrollment pipeline can make it true.
    """
    subject = await create_subject(client, owner, external_id="user_1")

    response = await client.patch(
        f"/v1/console/subjects/{subject['id']}",
        json={"status": "enrolled"},
        headers=owner.auth,
    )

    # 400, not 422: this app maps schema validation to `invalid_request`.
    assert response.status_code == 400


# ── The happy path ────────────────────────────────────────────────────────────


async def test_a_three_shot_enrollment_creates_a_versioned_profile(
    client: AsyncClient, owner: Account
) -> None:
    subject = await create_subject(client, owner, external_id="user_1")

    response = await enroll(client, owner, subject["id"], images=frames(1, 3))

    assert response.status_code == 201, response.text
    body = response.json()

    assert body["status"] == "succeeded"
    assert body["id"].startswith("enr_")
    profile = body["face_profile"]
    assert profile["version"] == 1
    assert profile["status"] == "active"
    assert profile["template_count"] == 3
    assert 0.0 < profile["avg_quality_score"] <= 1.0
    # The model that produced the embeddings, recorded so a later upgrade is a
    # detectable mismatch rather than a silent accuracy collapse.
    assert profile["model"] == {"name": "fake", "version": "v1"}


async def test_the_subject_becomes_enrolled(client: AsyncClient, owner: Account) -> None:
    subject = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, subject["id"], images=frames(1, 3))

    detail = (await client.get(f"/v1/console/subjects/{subject['id']}", headers=owner.auth)).json()

    assert detail["status"] == "enrolled"
    assert detail["enrolled_at"] is not None
    assert detail["face_profile"]["version"] == 1


async def test_per_image_results_are_returned_on_success_too(
    client: AsyncClient, owner: Account
) -> None:
    """An integrator building a capture UI needs to know which frame was weak,
    not merely that the batch worked.
    """
    subject = await create_subject(client, owner, external_id="user_1")

    body = (await enroll(client, owner, subject["id"], images=frames(1, 3))).json()

    assert len(body["images"]) == 3
    for index, image in enumerate(body["images"]):
        assert image["index"] == index
        assert image["accepted"] is True
        assert image["quality_score"] > 0
        assert image["checks"], "the per-gate report is missing"
        assert image["bbox"] is not None


async def test_a_single_good_frame_is_enough(client: AsyncClient, owner: Account) -> None:
    subject = await create_subject(client, owner, external_id="user_1")

    response = await enroll(client, owner, subject["id"], images=[frame(1)])

    assert response.status_code == 201
    assert response.json()["face_profile"]["template_count"] == 1


async def test_only_the_frames_that_passed_become_templates(
    client: AsyncClient, owner: Account
) -> None:
    subject = await create_subject(client, owner, external_id="user_1")

    response = await enroll(
        client,
        owner,
        subject["id"],
        images=[frame(1, seed=1), frame(1, quality=0.15, seed=2), frame(1, seed=3)],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["face_profile"]["template_count"] == 2
    assert [image["accepted"] for image in body["images"]] == [True, False, True]


# ── Failure ───────────────────────────────────────────────────────────────────


async def test_an_unusable_batch_is_rejected_with_a_reason_per_frame(
    client: AsyncClient, owner: Account
) -> None:
    subject = await create_subject(client, owner, external_id="user_1")

    response = await enroll(
        client,
        owner,
        subject["id"],
        images=[frame(1, quality=0.15), frame(1, brightness=0.02), frame(1, faces=0)],
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["message"], "a rejection with no guidance is not actionable"

    images = error["details"]["images"]
    assert len(images) == 3
    for image in images:
        assert image["accepted"] is False
        assert image["reason"]
        assert image["guidance"]


async def test_a_failed_enrollment_is_still_recorded(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    """Failure rates are how a customer learns their capture UI is broken.

    The attempt row is committed *before* the error is raised, so the diagnostic
    survives the very request that failed.
    """
    subject = await create_subject(client, owner, external_id="user_1")

    response = await enroll(client, owner, subject["id"], images=[frame(1, faces=0)])
    assert response.status_code == 422

    attempts = (
        await session.execute(select(EnrollmentAttempt).where(EnrollmentAttempt.status == "failed"))
    ).scalars()
    recorded = list(attempts)

    assert len(recorded) == 1
    assert recorded[0].failure_reason == "no_face_detected"
    assert recorded[0].accepted_count == 0
    assert recorded[0].image_count == 1
    assert recorded[0].id == response.json()["error"]["details"]["enrollment_id"]


async def test_a_failed_enrollment_leaves_the_subject_pending(
    client: AsyncClient, owner: Account
) -> None:
    subject = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, subject["id"], images=[frame(1, faces=0)])

    detail = (await client.get(f"/v1/console/subjects/{subject['id']}", headers=owner.auth)).json()

    assert detail["status"] == "pending"
    assert detail["face_profile"] is None


async def test_a_frame_with_a_bystander_is_refused(client: AsyncClient, owner: Account) -> None:
    subject = await create_subject(client, owner, external_id="user_1")

    response = await enroll(client, owner, subject["id"], images=[frame(1, faces=2)])

    assert response.status_code == 422
    assert response.json()["error"]["details"]["images"][0]["reason"] == "multiple_faces"


async def test_more_images_than_the_global_limit_is_rejected_before_decoding(
    client: AsyncClient, owner: Account
) -> None:
    """Bounded in the schema so an oversized batch never reaches base64 decode."""
    subject = await create_subject(client, owner, external_id="user_1")

    response = await enroll(client, owner, subject["id"], images=frames(1, 9))

    assert response.status_code == 400


async def test_a_tenant_can_cap_templates_below_the_global_limit(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    """The organization's own ceiling, enforced in the service.

    Distinct from the schema bound above: that one protects the process, this
    one is the customer's policy about how much biometric data they hold.
    """
    settings_row = await session.get(OrgSettings, owner.organization_id)
    assert settings_row is not None
    settings_row.max_templates_per_profile = 2
    await session.commit()

    subject = await create_subject(client, owner, external_id="user_1")
    response = await enroll(client, owner, subject["id"], images=frames(1, 4))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "too_many_images"
    assert error["details"] == {"submitted": 4, "limit": 2}


async def test_a_corrupt_frame_is_rejected_with_its_index(
    client: AsyncClient, owner: Account
) -> None:
    subject = await create_subject(client, owner, external_id="user_1")

    response = await client.post(
        "/v1/console/enrollments",
        json={"subject_id": subject["id"], "images": [frame(1), "@@@not base64@@@"]},
        headers=owner.auth,
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_image"
    assert error["details"]["image_index"] == 1


async def test_enrolling_an_unknown_subject_is_a_404(client: AsyncClient, owner: Account) -> None:
    response = await enroll(client, owner, "sub_01ABCDEFGHJKMNPQRSTVWXYZ00")
    assert response.status_code == 404


# ── Re-enrollment and versioning ──────────────────────────────────────────────


async def test_re_enrolling_supersedes_the_previous_profile_and_keeps_history(
    client: AsyncClient, owner: Account
) -> None:
    subject = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, subject["id"], images=frames(1, 3))

    second = await enroll(client, owner, subject["id"], images=frames(1, 2))
    assert second.status_code == 201
    assert second.json()["face_profile"]["version"] == 2

    detail = (await client.get(f"/v1/console/subjects/{subject['id']}", headers=owner.auth)).json()

    assert detail["face_profile"]["version"] == 2
    assert detail["face_profile"]["template_count"] == 2

    history = detail["profile_history"]
    assert [profile["version"] for profile in history] == [2, 1]
    superseded = history[1]
    assert superseded["status"] == "superseded"
    assert superseded["superseded_at"] is not None


async def test_exactly_one_profile_is_active_after_re_enrolling(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    """Two active profiles would make verification non-deterministic. The
    database enforces this with a partial unique index; this proves the service
    does not fight it.
    """
    subject = await create_subject(client, owner, external_id="user_1")
    for _ in range(3):
        response = await enroll(client, owner, subject["id"], images=frames(1, 2))
        assert response.status_code == 201

    active = await session.scalar(
        select(func.count())
        .select_from(FaceProfile)
        .where(FaceProfile.subject_id == subject["id"], FaceProfile.status == "active")
    )
    total = await session.scalar(
        select(func.count()).select_from(FaceProfile).where(FaceProfile.subject_id == subject["id"])
    )

    assert active == 1
    assert total == 3


async def test_superseded_templates_are_destroyed_not_kept(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    """A superseded profile whose vectors survive could still match, which is
    exactly what versioning exists to prevent.
    """
    subject = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, subject["id"], images=frames(1, 3))
    await enroll(client, owner, subject["id"], images=frames(1, 2))

    remaining = await session.scalar(select(func.count()).select_from(FaceTemplate))

    assert remaining == 2, "templates from the superseded profile were not destroyed"


async def test_versions_are_never_reused(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    """An audit trail with two different "version 2" profiles cannot explain a
    past decision.
    """
    subject = await create_subject(client, owner, external_id="user_1")
    for _ in range(3):
        await enroll(client, owner, subject["id"], images=frames(1, 2))

    versions = list(
        (
            await session.execute(
                select(FaceProfile.version).where(FaceProfile.subject_id == subject["id"])
            )
        ).scalars()
    )

    assert sorted(versions) == [1, 2, 3]


async def test_replace_existing_false_refuses_to_overwrite(
    client: AsyncClient, owner: Account
) -> None:
    subject = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, subject["id"], images=frames(1, 3))

    response = await enroll(
        client, owner, subject["id"], images=frames(1, 3), replace_existing=False
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "already_enrolled"
    assert "override_with" in error["details"]


# ── Duplicate detection ───────────────────────────────────────────────────────


async def test_the_same_face_under_a_second_identity_is_surfaced_as_a_decision(
    client: AsyncClient, owner: Account
) -> None:
    """Not a silent success. The error names the resolution, because an error
    that describes a problem without describing the fix is half an error.
    """
    first = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, first["id"], images=frames(5, 3))

    second = await create_subject(client, owner, external_id="user_2")
    response = await enroll(client, owner, second["id"], images=frames(5, 3))

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "duplicate_face_detected"
    details = error["details"]
    assert details["matched_subject_id"] == first["id"]
    assert details["similarity"] > details["threshold"]
    assert details["override_with"] == "options.check_duplicates=false"


async def test_a_duplicate_attempt_is_recorded_and_creates_no_profile(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    first = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, first["id"], images=frames(5, 3))

    second = await create_subject(client, owner, external_id="user_2")
    await enroll(client, owner, second["id"], images=frames(5, 3))

    attempt = (
        await session.execute(
            select(EnrollmentAttempt).where(EnrollmentAttempt.status == "duplicate_detected")
        )
    ).scalar_one()

    assert attempt.duplicate_subject_id == first["id"]
    assert attempt.duplicate_similarity is not None
    assert attempt.face_profile_id is None

    profiles = await session.scalar(
        select(func.count()).select_from(FaceProfile).where(FaceProfile.subject_id == second["id"])
    )
    assert profiles == 0


async def test_duplicate_detection_can_be_overridden_deliberately(
    client: AsyncClient, owner: Account
) -> None:
    """Identical twins exist, and so do customers who have decided the trade-off
    for themselves. The check is a default, not a wall.
    """
    first = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, first["id"], images=frames(5, 3))

    second = await create_subject(client, owner, external_id="user_2")
    response = await enroll(
        client, owner, second["id"], images=frames(5, 3), check_duplicates=False
    )

    assert response.status_code == 201


async def test_a_different_face_is_not_a_duplicate(client: AsyncClient, owner: Account) -> None:
    first = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, first["id"], images=frames(5, 3))

    second = await create_subject(client, owner, external_id="user_2")
    response = await enroll(client, owner, second["id"], images=frames(6, 3))

    assert response.status_code == 201


async def test_re_enrolling_yourself_is_never_a_duplicate_of_yourself(
    client: AsyncClient, owner: Account
) -> None:
    """The subject is excluded from its own duplicate search — otherwise nobody
    could ever re-enroll.
    """
    subject = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, subject["id"], images=frames(5, 3))

    response = await enroll(client, owner, subject["id"], images=frames(5, 3))

    assert response.status_code == 201
    assert response.json()["face_profile"]["version"] == 2


async def test_a_revoked_profile_does_not_block_a_new_enrollment(
    client: AsyncClient, owner: Account
) -> None:
    """Revoked data is data the customer asked us to stop matching against.
    Treating it as a duplicate would block a legitimate re-onboarding.
    """
    first = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, first["id"], images=frames(5, 3))
    await client.delete(f"/v1/console/subjects/{first['id']}/face-profile", headers=owner.auth)

    second = await create_subject(client, owner, external_id="user_2")
    response = await enroll(client, owner, second["id"], images=frames(5, 3))

    assert response.status_code == 201


# ── Deletion and retention ────────────────────────────────────────────────────


async def test_deleting_a_subject_physically_destroys_its_templates(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    """Checked against the table, not the response. A soft-deleted biometric
    template is still retained biometric data.
    """
    subject = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, subject["id"], images=frames(1, 3))

    assert await session.scalar(select(func.count()).select_from(FaceTemplate)) == 3

    response = await client.delete(f"/v1/console/subjects/{subject['id']}", headers=owner.auth)

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "templates_destroyed": 3}
    assert await session.scalar(select(func.count()).select_from(FaceTemplate)) == 0


async def test_deleting_a_subject_keeps_the_row_for_audit_continuity(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    """Past verification sessions and audit entries must still resolve. There is
    no biometric data left in the row.
    """
    subject = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, subject["id"], images=frames(1, 3))
    await client.delete(f"/v1/console/subjects/{subject['id']}", headers=owner.auth)

    row = await session.get(Subject, subject["id"])

    assert row is not None
    assert row.deleted_at is not None
    assert (
        await client.get(f"/v1/console/subjects/{subject['id']}", headers=owner.auth)
    ).status_code == 404


async def test_the_same_external_id_can_be_reused_after_deletion(
    client: AsyncClient, owner: Account
) -> None:
    """The customer's identifier is not something they can change. Deleting a
    subject must not poison it forever.
    """
    first = await create_subject(client, owner, external_id="user_84213")
    await client.delete(f"/v1/console/subjects/{first['id']}", headers=owner.auth)

    response = await client.post(
        "/v1/console/subjects",
        json={"external_id": "user_84213"},
        headers=owner.auth,
    )

    assert response.status_code == 201, response.text
    assert response.json()["id"] != first["id"]


async def test_deletion_writes_an_audit_entry(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    subject = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, subject["id"], images=frames(1, 3))
    await client.delete(f"/v1/console/subjects/{subject['id']}", headers=owner.auth)

    entry = (
        await session.execute(select(AuditLog).where(AuditLog.action == "subject.deleted"))
    ).scalar_one()

    assert entry.resource_id == subject["id"]
    assert entry.changes is not None
    assert entry.changes["templates_destroyed"] == 3
    assert entry.actor_email == owner.email


async def test_revoking_a_profile_keeps_the_subject_but_destroys_the_templates(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    subject = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, subject["id"], images=frames(1, 3))

    response = await client.delete(
        f"/v1/console/subjects/{subject['id']}/face-profile", headers=owner.auth
    )

    assert response.status_code == 200
    assert response.json()["templates_destroyed"] == 3
    assert await session.scalar(select(func.count()).select_from(FaceTemplate)) == 0

    detail = (await client.get(f"/v1/console/subjects/{subject['id']}", headers=owner.auth)).json()
    assert detail["status"] == "pending"
    assert detail["face_profile"] is None
    # The history survives, so an old decision is still explicable.
    assert detail["profile_history"][0]["status"] == "revoked"


async def test_revoking_when_there_is_no_profile_is_a_404(
    client: AsyncClient, owner: Account
) -> None:
    subject = await create_subject(client, owner, external_id="user_1")

    response = await client.delete(
        f"/v1/console/subjects/{subject['id']}/face-profile", headers=owner.auth
    )

    assert response.status_code == 404


async def test_raw_frames_are_never_persisted(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    """Retention is off by default and there is no object store yet, so no
    template may carry an image reference. Asserted against storage, because
    that is the only place the claim can actually be checked.
    """
    subject = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, subject["id"], images=frames(1, 3))

    stored = list((await session.execute(select(FaceTemplate.image_ref))).scalars())

    assert stored == [None, None, None]


async def test_templates_carry_the_quality_measurements_behind_them(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    """So a later accuracy investigation can ask "were the failing subjects
    enrolled from dim frames?" without re-running anything.
    """
    subject = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, subject["id"], images=frames(1, 3))

    template = (await session.execute(select(FaceTemplate).limit(1))).scalar_one()

    assert template.quality_score > 0
    assert template.sharpness is not None
    assert template.brightness is not None
    assert template.bbox is not None
    assert template.pose_yaw is not None


# ── Listing and history ───────────────────────────────────────────────────────


async def test_the_enrollment_list_includes_failures(client: AsyncClient, owner: Account) -> None:
    subject = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, subject["id"], images=frames(1, 3))
    await enroll(client, owner, subject["id"], images=[frame(1, faces=0)])

    body = (await client.get("/v1/console/enrollments", headers=owner.auth)).json()

    statuses = [item["status"] for item in body["data"]]
    assert sorted(statuses) == ["failed", "succeeded"]
    assert all(item["subject_external_id"] == "user_1" for item in body["data"])


async def test_the_enrollment_list_can_be_filtered_by_status(
    client: AsyncClient, owner: Account
) -> None:
    subject = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, subject["id"], images=frames(1, 3))
    await enroll(client, owner, subject["id"], images=[frame(1, faces=0)])

    body = (await client.get("/v1/console/enrollments?status=failed", headers=owner.auth)).json()

    assert len(body["data"]) == 1
    assert body["data"][0]["status"] == "failed"


async def test_enrollment_detail_returns_the_quality_report_recorded_at_the_time(
    client: AsyncClient, owner: Account
) -> None:
    subject = await create_subject(client, owner, external_id="user_1")
    created = (await enroll(client, owner, subject["id"], images=frames(1, 3))).json()

    body = (await client.get(f"/v1/console/enrollments/{created['id']}", headers=owner.auth)).json()

    assert body["id"] == created["id"]
    assert body["face_profile_id"] == created["face_profile"]["id"]
    assert len(body["images"]) == 3
    assert body["images"][0]["checks"]


async def test_enrollment_history_survives_subject_deletion(
    client: AsyncClient, owner: Account
) -> None:
    """The attempt row outlives the subject, with a null external_id rather than
    vanishing from the record.
    """
    subject = await create_subject(client, owner, external_id="user_1")
    await enroll(client, owner, subject["id"], images=frames(1, 3))
    await client.delete(f"/v1/console/subjects/{subject['id']}", headers=owner.auth)

    body = (await client.get("/v1/console/enrollments", headers=owner.auth)).json()

    assert len(body["data"]) == 1
    assert body["data"][0]["status"] == "succeeded"


# ── Authorization ─────────────────────────────────────────────────────────────


async def test_a_viewer_cannot_enroll(client: AsyncClient, owner: Account) -> None:
    viewer = await invite_and_join(
        client, inviter=owner, email="viewer@acme.example.com", role="viewer"
    )
    subject = await create_subject(client, owner, external_id="user_1")

    response = await enroll(client, viewer, subject["id"], images=frames(1, 3))

    assert response.status_code == 403


async def test_a_viewer_cannot_create_or_delete_subjects(
    client: AsyncClient, owner: Account
) -> None:
    viewer = await invite_and_join(
        client, inviter=owner, email="viewer@acme.example.com", role="viewer"
    )
    subject = await create_subject(client, owner, external_id="user_1")

    created = await client.post(
        "/v1/console/subjects", json={"external_id": "sneaky"}, headers=viewer.auth
    )
    deleted = await client.delete(f"/v1/console/subjects/{subject['id']}", headers=viewer.auth)

    assert created.status_code == 403
    assert deleted.status_code == 403


async def test_a_developer_can_enroll_but_not_delete_subjects(
    client: AsyncClient, owner: Account
) -> None:
    """The Developer role integrates and operates; deletion of biometric data is
    an Admin decision.
    """
    developer = await invite_and_join(
        client, inviter=owner, email="dev@acme.example.com", role="developer"
    )
    subject = await create_subject(client, developer, external_id="user_1")

    enrolled = await enroll(client, developer, subject["id"], images=frames(1, 3))
    deleted = await client.delete(f"/v1/console/subjects/{subject['id']}", headers=developer.auth)

    assert enrolled.status_code == 201
    assert deleted.status_code == 403


async def test_an_unauthenticated_request_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/console/enrollments", json={"subject_id": "sub_x", "images": [frame(1)]}
    )
    assert response.status_code == 401


async def test_no_template_outlives_its_active_profile(
    client: AsyncClient, owner: Account, session: AsyncSession
) -> None:
    """The invariant the duplicate search leans on.

    Every path that retires a profile — supersede, revoke, subject delete —
    physically destroys its templates, so a consistent database has no template
    belonging to a non-active profile. `_search_pgvector` relies on this to keep
    the ANN query single-table, which is the difference between an index scan
    and a sequential scan over every template in the database.
    """
    keep = await create_subject(client, owner, external_id="keep")
    superseded = await create_subject(client, owner, external_id="superseded")
    revoked = await create_subject(client, owner, external_id="revoked")
    removed = await create_subject(client, owner, external_id="removed")

    await enroll(client, owner, keep["id"], images=frames(1, 2))
    await enroll(client, owner, superseded["id"], images=frames(2, 2))
    await enroll(client, owner, superseded["id"], images=frames(2, 3))
    await enroll(client, owner, revoked["id"], images=frames(3, 2))
    await client.delete(f"/v1/console/subjects/{revoked['id']}/face-profile", headers=owner.auth)
    await enroll(client, owner, removed["id"], images=frames(4, 2))
    await client.delete(f"/v1/console/subjects/{removed['id']}", headers=owner.auth)

    orphaned = await session.scalar(
        select(func.count())
        .select_from(FaceTemplate)
        .join(FaceProfile, FaceTemplate.face_profile_id == FaceProfile.id)
        .where(FaceProfile.status != "active")
    )

    assert orphaned == 0, "a template outlived the profile that owned it"


async def test_the_nearest_match_is_reported_when_several_subjects_are_enrolled(
    client: AsyncClient, owner: Account
) -> None:
    """Candidates collapse to one row per subject, keeping their best template,
    so a crowded neighbourhood cannot hide the actual match.
    """
    for identity in range(20, 26):
        subject = await create_subject(client, owner, external_id=f"user_{identity}")
        response = await enroll(client, owner, subject["id"], images=frames(identity, 3))
        assert response.status_code == 201

    target = (await client.get("/v1/console/subjects/ext_user_23", headers=owner.auth)).json()
    intruder = await create_subject(client, owner, external_id="intruder")

    response = await enroll(client, owner, intruder["id"], images=frames(23, 2))

    assert response.status_code == 409
    assert response.json()["error"]["details"]["matched_subject_id"] == target["id"]
