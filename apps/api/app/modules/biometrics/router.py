"""Subject and enrollment endpoints.

Mounted on the console prefix (`/v1/console/...`, JWT) in this phase. The public
`/v1/...` surface with API-key authentication arrives in Phase 7, and mounting
it is a routing change, not a rewrite: the handlers below build an `Actor` and
hand it to a service that has no idea which authentication plane produced it.
That is what makes "the API path produces an identical profile to the console
path" structurally true rather than something to test for.

Handlers stay thin on purpose (docs/05-architecture.md §2): resolve the
principal, call one service method, serialize. Every decision lives in
`service.py`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.dependencies.auth import Principal, require_permission
from app.dependencies.db import get_db
from app.modules.biometrics.engine.base import FaceEngine
from app.modules.biometrics.engine.registry import get_engine
from app.modules.biometrics.models import EnrollmentAttempt, FaceProfile, Subject
from app.modules.biometrics.repository import EnrollmentAttemptRepository
from app.modules.biometrics.schemas import (
    EnrollmentDetail,
    EnrollmentImageResult,
    EnrollmentListItem,
    EnrollmentRequest,
    EnrollmentResponse,
    FaceProfileResponse,
    ModelRef,
    SubjectCreate,
    SubjectDetail,
    SubjectResponse,
    SubjectUpdate,
)
from app.modules.biometrics.service import Actor, EnrollmentService, SubjectService
from app.shared.base_repository import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    decode_cursor,
    encode_cursor,
)
from app.shared.schemas import Page, Pagination

router = APIRouter(tags=["Biometrics"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
Engine = Annotated[FaceEngine, Depends(get_engine)]

ReadSubjects = Annotated[Principal, Depends(require_permission(Permission.SUBJECT_READ))]
WriteSubjects = Annotated[Principal, Depends(require_permission(Permission.SUBJECT_WRITE))]
DeleteSubjects = Annotated[Principal, Depends(require_permission(Permission.SUBJECT_DELETE))]
WriteEnrollments = Annotated[Principal, Depends(require_permission(Permission.ENROLLMENT_WRITE))]


def _actor(principal: Principal, request: Request) -> Actor:
    """Everything the audit trail needs, gathered once."""
    return Actor(
        organization_id=principal.require_organization,
        user_id=principal.user_id,
        email=principal.email,
        source="console",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
    )


# ── Subjects ──────────────────────────────────────────────────────────────────


@router.post(
    "/subjects",
    response_model=SubjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a subject",
    description=(
        "Creates the record a face is later enrolled against. Status is `pending` until "
        "an enrollment succeeds — a subject is not an identity until it has biometrics."
    ),
)
async def create_subject(
    body: SubjectCreate,
    principal: WriteSubjects,
    session: DbSession,
    request: Request,
) -> SubjectResponse:
    service = SubjectService(session, _actor(principal, request))
    subject = await service.create(
        external_id=body.external_id,
        display_name=body.display_name,
        consent_reference=body.consent_reference,
        metadata=body.metadata,
    )
    return _subject_response(subject)


@router.get(
    "/subjects/{subject_id}",
    response_model=SubjectDetail,
    summary="Retrieve a subject",
    description="Accepts a subject id or `ext_<your external id>`.",
)
async def get_subject(
    subject_id: str,
    principal: ReadSubjects,
    session: DbSession,
    request: Request,
) -> SubjectDetail:
    service = SubjectService(session, _actor(principal, request))
    subject = await service.resolve(subject_id)

    history = await service.profile_history(subject.id)
    active = next((profile for profile in history if profile.status == "active"), None)

    return SubjectDetail(
        **_subject_response(subject).model_dump(),
        face_profile=_profile_response(active) if active else None,
        profile_history=[_profile_response(profile) for profile in history],
    )


@router.patch(
    "/subjects/{subject_id}",
    response_model=SubjectResponse,
    summary="Update a subject",
)
async def update_subject(
    subject_id: str,
    body: SubjectUpdate,
    principal: WriteSubjects,
    session: DbSession,
    request: Request,
) -> SubjectResponse:
    service = SubjectService(session, _actor(principal, request))
    subject = await service.update(
        subject_id,
        display_name=body.display_name,
        status=body.status,
        consent_reference=body.consent_reference,
        metadata=body.metadata,
    )
    return _subject_response(subject)


@router.delete(
    "/subjects/{subject_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a subject and all of its biometric data",
    description=(
        "Templates are **physically deleted**, not flagged — a soft-deleted biometric "
        "template is still retained biometric data. The subject row is tombstoned so "
        "past verification sessions and audit entries still resolve. Irreversible."
    ),
)
async def delete_subject(
    subject_id: str,
    principal: DeleteSubjects,
    session: DbSession,
    request: Request,
) -> dict[str, object]:
    service = SubjectService(session, _actor(principal, request))
    destroyed = await service.delete(subject_id)
    return {"deleted": True, "templates_destroyed": destroyed}


@router.delete(
    "/subjects/{subject_id}/face-profile",
    status_code=status.HTTP_200_OK,
    summary="Revoke the active face profile",
    description=(
        "Stops this subject being verifiable while keeping the record. Templates are "
        "destroyed, so the profile cannot be reinstated — the subject must re-enroll."
    ),
)
async def revoke_face_profile(
    subject_id: str,
    principal: DeleteSubjects,
    session: DbSession,
    request: Request,
) -> dict[str, object]:
    service = SubjectService(session, _actor(principal, request))
    destroyed = await service.revoke_profile(subject_id)
    return {"revoked": True, "templates_destroyed": destroyed}


# ── Enrollments ───────────────────────────────────────────────────────────────


@router.post(
    "/enrollments",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enroll a face",
    description=(
        "Runs detect, quality gating, embedding and duplicate detection, then creates a "
        "profile. Re-enrolling supersedes the previous profile and increments its "
        "version.\n\n"
        "Per-image results are returned on success as well as failure, so a capture UI "
        "can tell the user *which* frame was weak.\n\n"
        "**409 `duplicate_face_detected`** means the face already belongs to another "
        "subject. That is a decision to surface, not an error to retry."
    ),
    responses={
        409: {"description": "Duplicate face, or the subject is already enrolled"},
        422: {"description": "No usable frame — see `details.images` for per-frame reasons"},
    },
)
async def create_enrollment(
    body: EnrollmentRequest,
    principal: WriteEnrollments,
    session: DbSession,
    request: Request,
    engine: Engine,
) -> EnrollmentResponse:
    service = EnrollmentService(session, _actor(principal, request), engine)
    attempt = await service.enroll(
        subject_ref=body.subject_id,
        images=body.images,
        check_duplicates=body.options.check_duplicates,
        min_quality=body.options.min_quality,
        replace_existing=body.options.replace_existing,
    )

    profile: FaceProfile | None = None
    if attempt.face_profile_id:
        profile = await session.get(FaceProfile, attempt.face_profile_id)

    return EnrollmentResponse(
        id=attempt.id,
        status=attempt.status,
        subject_id=attempt.subject_id,
        face_profile=_profile_response(profile) if profile else None,
        images=_image_results(attempt),
        failure_reason=attempt.failure_reason,
        latency_ms=attempt.latency_ms,
        created_at=attempt.created_at,
    )


@router.get(
    "/enrollments",
    response_model=Page[EnrollmentListItem],
    summary="List enrollment attempts",
    description=(
        "Includes failures. Enrollment failure rate is how a customer learns their "
        "capture UI is broken, so it is not filtered out by default."
    ),
)
async def list_enrollments(
    principal: ReadSubjects,
    session: DbSession,
    subject_id: str | None = None,
    attempt_status: Annotated[str | None, Query(alias="status")] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[EnrollmentListItem]:
    organization_id = principal.require_organization

    # Left join so an attempt whose subject was later deleted still lists, with
    # a null external_id rather than vanishing from the history.
    statement = (
        select(EnrollmentAttempt, Subject.external_id)
        .outerjoin(Subject, EnrollmentAttempt.subject_id == Subject.id)
        .where(EnrollmentAttempt.organization_id == organization_id)
    )
    if subject_id:
        statement = statement.where(EnrollmentAttempt.subject_id == subject_id)
    if attempt_status:
        statement = statement.where(EnrollmentAttempt.status == attempt_status)
    if cursor:
        statement = statement.where(EnrollmentAttempt.id < decode_cursor(cursor))

    statement = statement.order_by(EnrollmentAttempt.id.desc()).limit(limit + 1)
    rows = (await session.execute(statement)).all()

    has_more = len(rows) > limit
    page = rows[:limit]
    items = [_list_item(attempt, external_id) for attempt, external_id in page]

    return Page(
        data=items,
        pagination=Pagination(
            next_cursor=encode_cursor(page[-1][0].id) if has_more and page else None,
            has_more=has_more,
            limit=limit,
        ),
    )


@router.get(
    "/enrollments/{enrollment_id}",
    response_model=EnrollmentDetail,
    summary="Enrollment attempt detail",
    description="Includes the full per-image quality report recorded at the time.",
)
async def get_enrollment(
    enrollment_id: str,
    principal: ReadSubjects,
    session: DbSession,
    request: Request,
) -> EnrollmentDetail:
    repository = EnrollmentAttemptRepository(session, principal.require_organization)
    attempt = await repository.get_or_404(enrollment_id)

    external_id: str | None = None
    if attempt.subject_id:
        subject = await session.get(Subject, attempt.subject_id)
        external_id = subject.external_id if subject else None

    base = _list_item(attempt, external_id)
    return EnrollmentDetail(
        **base.model_dump(),
        face_profile_id=attempt.face_profile_id,
        duplicate_similarity=(
            float(attempt.duplicate_similarity) if attempt.duplicate_similarity else None
        ),
        images=_image_results(attempt),
        enrolled_by_user_id=attempt.enrolled_by_user_id,
    )


# ── Serialization ─────────────────────────────────────────────────────────────


def _subject_response(subject: Subject) -> SubjectResponse:
    return SubjectResponse(
        id=subject.id,
        external_id=subject.external_id,
        display_name=subject.display_name,
        status=subject.status,
        consent_reference=subject.consent_reference,
        metadata=subject.subject_metadata,
        verification_count=subject.verification_count,
        enrolled_at=subject.enrolled_at,
        last_verified_at=subject.last_verified_at,
        created_at=subject.created_at,
    )


def _profile_response(profile: FaceProfile) -> FaceProfileResponse:
    return FaceProfileResponse(
        id=profile.id,
        version=profile.version,
        status=profile.status,
        template_count=profile.template_count,
        avg_quality_score=(
            float(profile.avg_quality_score) if profile.avg_quality_score is not None else None
        ),
        model=ModelRef(name=profile.model_name, version=profile.model_version),
        created_at=profile.created_at,
        superseded_at=profile.superseded_at,
        revoked_at=profile.revoked_at,
    )


def _list_item(attempt: EnrollmentAttempt, external_id: str | None) -> EnrollmentListItem:
    return EnrollmentListItem(
        id=attempt.id,
        subject_id=attempt.subject_id,
        subject_external_id=external_id,
        status=attempt.status,
        failure_reason=attempt.failure_reason,
        image_count=attempt.image_count,
        accepted_count=attempt.accepted_count,
        duplicate_subject_id=attempt.duplicate_subject_id,
        latency_ms=attempt.latency_ms,
        source=attempt.source,
        created_at=attempt.created_at,
    )


def _image_results(attempt: EnrollmentAttempt) -> list[EnrollmentImageResult]:
    """Re-hydrate the stored per-image report.

    Validated on the way out rather than trusted: the column is JSON, and a
    report written by an older build must not be able to break this response.
    """
    report = attempt.quality_report or {}
    images = report.get("images") if isinstance(report, dict) else None
    if not isinstance(images, list):
        return []
    return [EnrollmentImageResult.model_validate(entry) for entry in images]
