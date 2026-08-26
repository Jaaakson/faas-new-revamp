"""Subject lifecycle and the enrollment pipeline.

Two services, one transaction boundary each. Routers call these; nothing calls
the repositories directly.

The enrollment pipeline is the reason this file exists, and its ordering is the
design:

    decode -> detect -> gate -> embed -> deduplicate -> supersede -> persist

Every stage before `persist` can fail, and each failure is recorded as an
attempt row rather than discarded. Enrollment failure rates are how a customer
learns their capture UI is broken; throwing that data away would make the
product's most useful diagnostic invisible.

The CPU-bound stages run in a worker thread, once for the whole batch. Blocking
the event loop for the ~600 ms a five-shot enrollment costs would stall every
other request in the process, including health checks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.modules.biometrics.engine.base import FaceEngine
from app.modules.biometrics.images import load_images
from app.modules.biometrics.models import (
    AuditAction,
    AuditLog,
    EnrollmentAttempt,
    FaceProfile,
    FaceTemplate,
    Subject,
)
from app.modules.biometrics.pipeline import BatchOutcome, process_frames
from app.modules.biometrics.repository import (
    DuplicateHit,
    EnrollmentAttemptRepository,
    FaceProfileRepository,
    FaceTemplateRepository,
    SubjectRepository,
)
from app.modules.identity.models import OrgSettings
from app.shared.utils import ids

logger = structlog.get_logger(__name__)

# `ext_` lets an integrator address a subject by their own identifier without a
# lookup round trip (docs/07-api-design.md §3.1).
EXTERNAL_ID_PREFIX = "ext_"


@dataclass(frozen=True, slots=True)
class Actor:
    """Who is performing the action, independent of how they authenticated.

    A console JWT and (from Phase 7) an API key both collapse to this, so the
    service never learns which plane a request arrived on — which is what makes
    "the API path produces an identical profile to the console path" true by
    construction rather than by testing.
    """

    organization_id: str
    user_id: str | None = None
    email: str | None = None
    source: str = "api"
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None

    @property
    def actor_type(self) -> str:
        return "user" if self.user_id else "api_key"


def write_audit(
    session: AsyncSession,
    actor: Actor,
    action: str,
    resource_type: str,
    resource_id: str,
    changes: dict[str, Any],
) -> None:
    """Append an audit entry to the *current* transaction.

    Not committed here. Written in the same transaction as the change it
    records, so a committed change without its audit entry is not representable
    (docs/09-security.md §6).
    """
    session.add(
        AuditLog(
            organization_id=actor.organization_id,
            actor_type=actor.actor_type,
            actor_id=actor.user_id,
            actor_email=actor.email,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            changes=changes,
            ip_address=actor.ip_address,
            user_agent=actor.user_agent,
            request_id=actor.request_id,
        )
    )


class SubjectService:
    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self.session = session
        self.actor = actor
        self.subjects = SubjectRepository(session, actor.organization_id)
        self.profiles = FaceProfileRepository(session, actor.organization_id)
        self.templates = FaceTemplateRepository(session, actor.organization_id)

    async def create(
        self,
        *,
        external_id: str,
        display_name: str | None,
        consent_reference: str | None,
        metadata: dict[str, Any],
    ) -> Subject:
        if await self.subjects.external_id_exists(external_id):
            raise ConflictError(
                f"A subject with external_id '{external_id}' already exists.",
                code="subject_already_exists",
                details={"external_id": external_id},
            )

        subject = Subject(
            organization_id=self.actor.organization_id,
            external_id=external_id,
            display_name=display_name,
            consent_reference=consent_reference,
            consent_at=datetime.now(tz=UTC) if consent_reference else None,
            subject_metadata=metadata,
            status="pending",
        )
        self.session.add(subject)
        await self.session.flush()

        write_audit(
            self.session,
            self.actor,
            AuditAction.SUBJECT_CREATED,
            "subject",
            subject.id,
            {"external_id": external_id},
        )
        await self.session.commit()
        return subject

    async def resolve(self, identifier: str) -> Subject:
        """Accept either a subject id or `ext_<external_id>`."""
        if identifier.startswith(EXTERNAL_ID_PREFIX):
            external_id = identifier[len(EXTERNAL_ID_PREFIX) :]
            subject = await self.subjects.get_by_external_id(external_id)
            if subject is None:
                raise NotFoundError(
                    f"No subject with external_id '{external_id}'.",
                    details={"resource": "subject", "external_id": external_id},
                )
            return subject
        return await self.subjects.get_or_404(identifier)

    async def update(self, identifier: str, **values: Any) -> Subject:
        subject = await self.resolve(identifier)
        changed: dict[str, Any] = {}
        for field, value in values.items():
            if value is None:
                continue
            column = "subject_metadata" if field == "metadata" else field
            if getattr(subject, column) != value:
                changed[field] = value
                setattr(subject, column, value)

        if changed:
            if "consent_reference" in changed:
                subject.consent_at = datetime.now(tz=UTC)
            await self.session.commit()
        return subject

    async def delete(self, identifier: str) -> int:
        """Destroy the biometric data; keep the record.

        The split is deliberate and comes straight from the retention policy
        (docs/09-security.md §5): templates are physically deleted, and the
        subject row is soft-deleted so that past verification sessions and audit
        entries still resolve to something. Tombstoning the row is not retention
        of biometric data — there is no biometric data left in it.

        Returns the number of templates destroyed, which is what the audit entry
        and the deletion test both need.
        """
        subject = await self.resolve(identifier)

        destroyed = await self.templates.delete_for_subject(subject.id)
        for profile in await self.profiles.list_for_subject(subject.id):
            profile.status = "revoked"
            profile.revoked_at = datetime.now(tz=UTC)
            profile.template_count = 0

        subject.deleted_at = datetime.now(tz=UTC)
        subject.status = "suspended"

        write_audit(
            self.session,
            self.actor,
            AuditAction.SUBJECT_DELETED,
            "subject",
            subject.id,
            {"external_id": subject.external_id, "templates_destroyed": destroyed},
        )
        await self.session.commit()
        logger.info(
            "subject_deleted",
            subject_id=subject.id,
            templates_destroyed=destroyed,
            organization_id=self.actor.organization_id,
        )
        return destroyed

    async def revoke_profile(self, identifier: str) -> int:
        """Revoke the active profile, keeping the subject.

        Distinct from deletion: the customer wants this person to stop being
        verifiable, not to disappear. Templates still go — a revoked profile
        whose vectors remain is a profile that can be un-revoked back into a
        working credential.
        """
        subject = await self.resolve(identifier)
        profile = await self.profiles.get_active(subject.id)
        if profile is None:
            raise NotFoundError(
                "This subject has no active face profile.",
                details={"resource": "face_profile", "subject_id": subject.id},
            )

        destroyed = await self.templates.delete_for_subject(subject.id)
        profile.status = "revoked"
        profile.revoked_at = datetime.now(tz=UTC)
        profile.template_count = 0

        subject.status = "pending"
        subject.enrolled_at = None

        write_audit(
            self.session,
            self.actor,
            AuditAction.FACE_PROFILE_REVOKED,
            "face_profile",
            profile.id,
            {"subject_id": subject.id, "templates_destroyed": destroyed},
        )
        await self.session.commit()
        return destroyed

    async def profile_history(self, subject_id: str) -> list[FaceProfile]:
        return await self.profiles.list_for_subject(subject_id)

    async def active_profile(self, subject_id: str) -> FaceProfile | None:
        return await self.profiles.get_active(subject_id)


class EnrollmentService:
    def __init__(self, session: AsyncSession, actor: Actor, engine: FaceEngine) -> None:
        self.session = session
        self.actor = actor
        self.engine = engine
        self.subjects = SubjectService(session, actor)
        self.profiles = FaceProfileRepository(session, actor.organization_id)
        self.templates = FaceTemplateRepository(session, actor.organization_id)
        self.attempts = EnrollmentAttemptRepository(session, actor.organization_id)

    async def enroll(
        self,
        *,
        subject_ref: str,
        images: list[str],
        check_duplicates: bool | None = None,
        min_quality: float | None = None,
        replace_existing: bool = True,
    ) -> EnrollmentAttempt:
        started = time.perf_counter()
        subject = await self.subjects.resolve(subject_ref)
        org_settings = await self._org_settings()

        existing = await self.profiles.get_active(subject.id)
        if existing is not None and not replace_existing:
            raise ConflictError(
                "This subject already has an active face profile.",
                code="already_enrolled",
                details={
                    "subject_id": subject.id,
                    "face_profile_id": existing.id,
                    "override_with": "options.replace_existing=true",
                },
            )

        if org_settings.store_raw_images:
            # Visible rather than silent. The setting exists in the schema and
            # in the console; the object store arrives in Phase 9. Until then a
            # tenant who switched it on must not be left believing their frames
            # are being retained.
            logger.warning(
                "image_retention_requested_but_unavailable",
                organization_id=self.actor.organization_id,
                subject_id=subject.id,
            )

        max_templates = org_settings.max_templates_per_profile
        if len(images) > max_templates:
            raise UnprocessableError(
                f"At most {max_templates} images may be enrolled per profile.",
                code="too_many_images",
                details={"submitted": len(images), "limit": max_templates},
            )

        # Decoding is I/O-shaped but CPU-bound; it belongs off the loop with the
        # rest of the frame work.
        frames = await run_in_threadpool(load_images, images)

        outcome: BatchOutcome = await run_in_threadpool(
            process_frames,
            self.engine,
            frames,
            strict=True,
            min_quality=min_quality,
        )

        accepted = outcome.accepted
        if not accepted:
            return await self._record_failure(
                subject=subject,
                outcome=outcome,
                started=started,
                reason=outcome.dominant_reason or "low_quality",
            )

        should_check = (
            org_settings.duplicate_check_enabled if check_duplicates is None else check_duplicates
        )
        if should_check:
            # The best frame, not all of them. Every accepted frame is the same
            # face; searching with each would multiply the cost of the only 1:N
            # query in the system for no additional signal.
            best = max(accepted, key=lambda frame: frame.quality_score)
            probe = best.embedding
            if probe is None:  # pragma: no cover - accepted implies embedded
                raise RuntimeError("an accepted frame is missing its embedding")
            hits = await self.templates.search_duplicates(
                probe,
                exclude_subject_id=subject.id,
                threshold=float(org_settings.duplicate_threshold),
                limit=3,
            )
            if hits:
                return await self._record_duplicate(
                    subject=subject,
                    outcome=outcome,
                    started=started,
                    hit=hits[0],
                    threshold=float(org_settings.duplicate_threshold),
                )

        return await self._record_success(
            subject=subject,
            outcome=outcome,
            started=started,
            previous=existing,
        )

    # ── Outcomes ──────────────────────────────────────────────────────────────

    async def _record_success(
        self,
        *,
        subject: Subject,
        outcome: BatchOutcome,
        started: float,
        previous: FaceProfile | None,
    ) -> EnrollmentAttempt:
        now = datetime.now(tz=UTC)
        accepted = outcome.accepted

        if previous is not None:
            # Superseded, not deleted. A verification decided last March must
            # still be explicable by the profile that was active then. The old
            # templates go with it — keeping them would mean a superseded
            # profile could still match, which is exactly what versioning is
            # supposed to prevent.
            previous.status = "superseded"
            previous.superseded_at = now
            await self.templates.delete_for_subject(subject.id)
            previous.template_count = 0
            # Flush before inserting the replacement: the partial unique index
            # permits one active profile per subject, and both rows are in
            # flight at once.
            await self.session.flush()

        model = self.engine.model
        version = await self.profiles.highest_version(subject.id) + 1
        average = sum(frame.quality_score for frame in accepted) / len(accepted)

        profile = FaceProfile(
            organization_id=self.actor.organization_id,
            subject_id=subject.id,
            status="active",
            version=version,
            model_name=model.name,
            model_version=model.version,
            embedding_dim=model.embedding_dim,
            template_count=len(accepted),
            avg_quality_score=_decimal(average, 3),
            enrolled_by_user_id=self.actor.user_id,
        )
        self.session.add(profile)
        await self.session.flush()

        for frame in accepted:
            report = frame.report
            face = frame.face
            self.session.add(
                FaceTemplate(
                    organization_id=self.actor.organization_id,
                    face_profile_id=profile.id,
                    embedding=frame.embedding,
                    quality_score=_decimal(frame.quality_score, 3),
                    sharpness=_gate_value(report, "sharpness"),
                    brightness=_gate_value(report, "brightness"),
                    pose_yaw=_decimal(face.pose.yaw, 2) if face else None,
                    pose_pitch=_decimal(face.pose.pitch, 2) if face else None,
                    pose_roll=_decimal(face.pose.roll, 2) if face else None,
                    bbox=face.bbox.as_dict() if face else None,
                    # Always null. There is no object store yet, so
                    # `store_raw_images` cannot be honoured; `enroll()` logs a
                    # warning when a tenant has it on. Writing frames somewhere
                    # undeclared to make the flag look implemented would be
                    # worse than leaving it unimplemented, and the retention
                    # guarantee only binds in the other direction: when the flag
                    # is off, nothing is stored. It never is.
                    image_ref=None,
                )
            )

        subject.status = "enrolled"
        subject.enrolled_at = now

        attempt = self._attempt_row(
            subject=subject,
            outcome=outcome,
            started=started,
            status="succeeded",
            face_profile_id=profile.id,
        )
        self.session.add(attempt)

        write_audit(
            self.session,
            self.actor,
            AuditAction.ENROLLMENT_COMPLETED,
            "face_profile",
            profile.id,
            {
                "subject_id": subject.id,
                "version": version,
                "template_count": len(accepted),
                "superseded": previous.id if previous else None,
            },
        )
        await self.session.commit()

        logger.info(
            "enrollment_succeeded",
            subject_id=subject.id,
            face_profile_id=profile.id,
            version=version,
            templates=len(accepted),
            latency_ms=attempt.latency_ms,
        )
        return attempt

    async def _record_failure(
        self,
        *,
        subject: Subject,
        outcome: BatchOutcome,
        started: float,
        reason: str,
    ) -> EnrollmentAttempt:
        attempt = self._attempt_row(
            subject=subject,
            outcome=outcome,
            started=started,
            status="failed",
            failure_reason=reason,
        )
        self.session.add(attempt)
        # Committed before raising. The attempt row is the diagnostic the
        # customer needs precisely when enrollment is failing; rolling it back
        # with the error would erase the evidence.
        await self.session.commit()

        guidance = next(
            (frame.guidance for frame in outcome.frames if frame.guidance),
            "Retake the photo.",
        )
        raise UnprocessableError(
            guidance,
            code=reason,
            details={
                "enrollment_id": attempt.id,
                "images": [frame.as_dict() for frame in outcome.frames],
            },
        )

    async def _record_duplicate(
        self,
        *,
        subject: Subject,
        outcome: BatchOutcome,
        started: float,
        hit: DuplicateHit,
        threshold: float,
    ) -> EnrollmentAttempt:
        attempt = self._attempt_row(
            subject=subject,
            outcome=outcome,
            started=started,
            status="duplicate_detected",
            failure_reason="duplicate_face",
        )
        attempt.duplicate_subject_id = hit.subject_id
        attempt.duplicate_similarity = _decimal(hit.similarity, 5)
        self.session.add(attempt)

        write_audit(
            self.session,
            self.actor,
            AuditAction.ENROLLMENT_DUPLICATE,
            "subject",
            subject.id,
            {"matched_subject_id": hit.subject_id, "similarity": round(hit.similarity, 5)},
        )
        await self.session.commit()

        logger.warning(
            "enrollment_duplicate_detected",
            subject_id=subject.id,
            matched_subject_id=hit.subject_id,
            similarity=round(hit.similarity, 5),
        )
        # A decision surfaced to the caller, not a silent success and not a
        # silent rejection. The error names the resolution because an error that
        # describes a problem without describing the fix is half an error.
        raise ConflictError(
            "This face closely matches an existing enrolled subject.",
            code="duplicate_face_detected",
            details={
                "enrollment_id": attempt.id,
                "matched_subject_id": hit.subject_id,
                "similarity": round(hit.similarity, 4),
                "threshold": threshold,
                "override_with": "options.check_duplicates=false",
            },
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _attempt_row(
        self,
        *,
        subject: Subject,
        outcome: BatchOutcome,
        started: float,
        status: str,
        failure_reason: str | None = None,
        face_profile_id: str | None = None,
    ) -> EnrollmentAttempt:
        return EnrollmentAttempt(
            id=ids.new_id(ids.ENROLLMENT),
            organization_id=self.actor.organization_id,
            subject_id=subject.id,
            face_profile_id=face_profile_id,
            status=status,
            failure_reason=failure_reason,
            image_count=len(outcome.frames),
            accepted_count=len(outcome.accepted),
            quality_report={"images": [frame.as_dict() for frame in outcome.frames]},
            enrolled_by_user_id=self.actor.user_id,
            source=self.actor.source,
            ip_address=self.actor.ip_address,
            user_agent=self.actor.user_agent,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    async def _org_settings(self) -> OrgSettings:
        """The tenant's enrollment policy.

        Read per enrollment rather than cached: a customer who tightens their
        duplicate threshold after an incident expects the next request to use
        it, and one indexed primary-key lookup is not the bottleneck in a
        pipeline that spends 600 ms in ONNX.
        """
        row = await self.session.get(OrgSettings, self.actor.organization_id)
        if row is None:
            raise NotFoundError("Organization settings not found.")
        return row


def _decimal(value: float, places: int) -> Decimal:
    return Decimal(str(round(value, places)))


def _gate_value(report: Any, name: str) -> Decimal | None:
    """Pull one gate's measured value out of a report, for the template row.

    Stored alongside the embedding so a later accuracy investigation can ask
    "were the failing subjects enrolled from dim frames?" without re-running
    anything.
    """
    if report is None:
        return None
    for gate in report.gates:
        if gate.name == name:
            return _decimal(gate.value, 3)
    return None
