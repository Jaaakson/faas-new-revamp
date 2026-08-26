"""The public `/v1` API.

This is the product: what a customer's backend actually calls.

Every handler here builds an `Actor` and delegates to the *same* service the
console uses. There is no second implementation of enrollment or verification,
so "the API path produces an identical result to the console path" is true by
construction rather than by testing. What differs is only how the caller is
identified — an API key with scopes instead of a JWT with a role — and that
difference is resolved before any of this code runs.

The public plane deliberately cannot reach organization settings, members,
billing, audit logs, or other API keys. A stolen key is confined to the
biometric operations it was scoped for, and cannot be used to widen its own
access or to discover the tenant's configuration.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.dependencies.auth import Principal, require_scope
from app.dependencies.db import get_db
from app.modules.biometrics.engine.base import FaceEngine
from app.modules.biometrics.engine.registry import get_engine
from app.modules.biometrics.schemas import (
    EnrollmentRequest,
    EnrollmentResponse,
    SubjectCreate,
    SubjectDetail,
    SubjectResponse,
    SubjectUpdate,
    VerificationRequest,
    VerificationResponse,
)
from app.modules.biometrics.service import Actor, EnrollmentService, SubjectService
from app.shared.schemas import Page, Pagination

router = APIRouter(tags=["Public API"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
Engine = Annotated[FaceEngine, Depends(get_engine)]

ReadSubjects = Annotated[Principal, Depends(require_scope(Permission.SUBJECT_READ))]
WriteSubjects = Annotated[Principal, Depends(require_scope(Permission.SUBJECT_WRITE))]
DeleteSubjects = Annotated[Principal, Depends(require_scope(Permission.SUBJECT_DELETE))]
WriteEnrollments = Annotated[Principal, Depends(require_scope(Permission.ENROLLMENT_WRITE))]
WriteVerifications = Annotated[Principal, Depends(require_scope(Permission.VERIFICATION_WRITE))]
ReadVerifications = Annotated[Principal, Depends(require_scope(Permission.VERIFICATION_READ))]


def _actor(principal: Principal, request: Request) -> Actor:
    """The same value object the console builds.

    `source="api"` and a null `user_id` are what make an audit entry say a
    machine did this, not a person — the key's creator must not appear to have
    taken an action their key took months later.
    """
    return Actor(
        organization_id=principal.require_organization,
        user_id=None,
        email=principal.email,
        source="api",
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
        "Registers one of your end users. `external_id` is **your** identifier, so "
        "nothing in your database has to change.\n\n"
        "The subject is `pending` until a face is enrolled - a subject is not an "
        "identity until it has biometrics."
    ),
)
async def create_subject(
    body: SubjectCreate,
    principal: WriteSubjects,
    session: DbSession,
    request: Request,
) -> SubjectResponse:
    from app.modules.biometrics.router import _subject_response

    subject = await SubjectService(session, _actor(principal, request)).create(
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
    from app.modules.biometrics.router import _profile_response, _subject_response

    service = SubjectService(session, _actor(principal, request))
    subject = await service.resolve(subject_id)
    history = await service.profile_history(subject.id)
    active = next((profile for profile in history if profile.status == "active"), None)

    return SubjectDetail(
        **_subject_response(subject).model_dump(),
        face_profile=_profile_response(active) if active else None,
        profile_history=[_profile_response(profile) for profile in history],
    )


@router.get(
    "/subjects",
    response_model=Page[SubjectResponse],
    summary="List subjects",
)
async def list_subjects(
    principal: ReadSubjects,
    session: DbSession,
    request: Request,
    subject_status: Annotated[str | None, Query(alias="status")] = None,
    external_id: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[SubjectResponse]:
    from sqlalchemy import select

    from app.modules.biometrics.models import Subject
    from app.modules.biometrics.router import _subject_response
    from app.shared.base_repository import decode_cursor, encode_cursor

    statement = select(Subject).where(
        Subject.organization_id == principal.require_organization,
        Subject.deleted_at.is_(None),
    )
    if subject_status:
        statement = statement.where(Subject.status == subject_status)
    if external_id:
        statement = statement.where(Subject.external_id == external_id)
    if cursor:
        statement = statement.where(Subject.id < decode_cursor(cursor))

    rows = list(await session.scalars(statement.order_by(Subject.id.desc()).limit(limit + 1)))
    has_more = len(rows) > limit
    page = rows[:limit]

    return Page(
        data=[_subject_response(row) for row in page],
        pagination=Pagination(
            next_cursor=encode_cursor(page[-1].id) if has_more and page else None,
            has_more=has_more,
            limit=limit,
        ),
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
    from app.modules.biometrics.router import _subject_response

    subject = await SubjectService(session, _actor(principal, request)).update(
        subject_id,
        display_name=body.display_name,
        status=body.status,
        consent_reference=body.consent_reference,
        metadata=body.metadata,
    )
    return _subject_response(subject)


@router.delete(
    "/subjects/{subject_id}",
    summary="Delete a subject and all of its biometric data",
    description=(
        "Templates are **physically deleted**, not flagged. The subject record is "
        "tombstoned so past verifications still resolve, and your `external_id` "
        "becomes reusable. Irreversible."
    ),
)
async def delete_subject(
    subject_id: str,
    principal: DeleteSubjects,
    session: DbSession,
    request: Request,
) -> dict[str, object]:
    destroyed = await SubjectService(session, _actor(principal, request)).delete(subject_id)
    return {"deleted": True, "templates_destroyed": destroyed}


@router.delete(
    "/subjects/{subject_id}/face-profile",
    summary="Revoke the active face profile",
)
async def revoke_face_profile(
    subject_id: str,
    principal: DeleteSubjects,
    session: DbSession,
    request: Request,
) -> dict[str, object]:
    destroyed = await SubjectService(session, _actor(principal, request)).revoke_profile(subject_id)
    return {"revoked": True, "templates_destroyed": destroyed}


# ── Enrollment ────────────────────────────────────────────────────────────────


@router.post(
    "/enrollments",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enroll a face",
    description=(
        "Runs detection, quality gating, embedding and duplicate detection, then "
        "creates a versioned face profile. Re-enrolling supersedes the previous "
        "profile and keeps it as history.\n\n"
        "Per-image results come back on success as well as failure, so your capture "
        "UI can tell the user *which* frame was weak.\n\n"
        "A **409 `duplicate_face_detected`** means the face already belongs to another "
        "subject. That is a decision to surface to a human, not an error to retry."
    ),
    responses={
        409: {"description": "Duplicate face, or the subject is already enrolled"},
        422: {"description": "No usable frame - see `details.images` for per-frame reasons"},
    },
)
async def create_enrollment(
    body: EnrollmentRequest,
    principal: WriteEnrollments,
    session: DbSession,
    request: Request,
    engine: Engine,
) -> EnrollmentResponse:
    from app.modules.biometrics.models import FaceProfile
    from app.modules.biometrics.router import _image_results, _profile_response

    attempt = await EnrollmentService(session, _actor(principal, request), engine).enroll(
        subject_ref=body.subject_id,
        images=body.images,
        check_duplicates=body.options.check_duplicates,
        min_quality=body.options.min_quality,
        replace_existing=body.options.replace_existing,
    )

    profile = (
        await session.get(FaceProfile, attempt.face_profile_id) if attempt.face_profile_id else None
    )
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


# ── Verification ──────────────────────────────────────────────────────────────


@router.post(
    "/verifications",
    response_model=VerificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify a face against a subject",
    description=(
        "The core endpoint.\n\n"
        "**A rejected verification is a `200`.** Read `decision`; only a failed "
        "*request* is a `4xx`. Conflating the two would force you to write exception "
        "handling around a normal business outcome.\n\n"
        "`inconclusive` is never collapsed into `rejected`. Telling your user they are "
        "not who they claim, when the truth is that the room is too dark, is both wrong "
        "and would corrupt your own fraud metrics with lighting problems.\n\n"
        "Send `Idempotency-Key` on retries: the first response is replayed for 24 hours "
        "without re-running the pipeline or charging your quota twice."
    ),
    responses={
        429: {"description": "Rate limit or monthly quota exhausted; carries `Retry-After`"},
    },
)
async def create_verification(
    body: VerificationRequest,
    principal: WriteVerifications,
    session: DbSession,
    request: Request,
    response: Response,
    engine: Engine,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    # Delegated wholesale: rate limiting, idempotency replay, quota and the
    # pipeline are one ordered sequence, and duplicating that ordering here is
    # how the two planes would silently drift apart.
    from app.modules.biometrics.verification_router import create_verification as run

    return await run(
        body=body,
        principal=principal,
        session=session,
        request=request,
        response=response,
        engine=engine,
        idempotency_key=idempotency_key,
    )


@router.get(
    "/verifications/{verification_id}",
    summary="Verification detail",
    description=(
        "Includes the threshold that was applied at the time. A later threshold change "
        "does not alter this record."
    ),
)
async def get_verification(
    verification_id: str,
    principal: ReadVerifications,
    session: DbSession,
) -> Any:
    from app.modules.biometrics.verification_router import get_verification as run

    return await run(
        verification_id=verification_id,
        principal=principal,
        session=session,
    )
