"""The core product loop: is this the person they claim to be?

    quota → load templates → detect → gate → liveness → embed → match → decide → persist

Three properties here are load-bearing, and each exists because collapsing it
would quietly corrupt something the customer relies on.

**The outcome is three-way, never two.** `rejected` means "a real face, but not
this person". `inconclusive` means "I could not decide" — no face, several
faces, too dark, liveness failed, no enrolled profile. Collapsing the second
into the first tells a customer's user *you are not who you say you are* when
the truth is *the room is too dark*, and it poisons the customer's fraud metrics
with lighting problems. `error` is a fourth state for our own failures, and it
is the only one that does not charge quota.

**A decision carries its threshold.** `threshold_applied` is written onto the
session row, so a threshold change next month cannot rewrite what happened this
month. An audit trail that moves is not an audit trail.

**Matching never goes near the ANN index.** Templates are loaded by profile id —
at most five rows — and compared exactly. Approximate-nearest-neighbour recall
is fine for finding duplicate candidates at enrollment; it is not something an
authentication decision should ride on (docs/06-database.md §4.3).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import numpy as np
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import NotFoundError
from app.core.plans import get_plan
from app.modules.biometrics import threshold as threshold_policy
from app.modules.biometrics.engine.base import Embedding, FaceEngine, best_match
from app.modules.biometrics.engine.quality import GATE_GUIDANCE
from app.modules.biometrics.images import decode_base64, decode_image
from app.modules.biometrics.liveness import (
    DisabledLivenessDetector,
    HeuristicLivenessDetector,
    LivenessDetector,
    LivenessReport,
)
from app.modules.biometrics.models import (
    FaceProfile,
    Subject,
    VerificationSession,
)
from app.modules.biometrics.repository import (
    FaceProfileRepository,
    FaceTemplateRepository,
    SubjectRepository,
)
from app.modules.biometrics.service import Actor
from app.modules.identity.models import Organization, OrgSettings

logger = structlog.get_logger(__name__)

# Reason codes. Stable strings — integrators branch on them and analytics groups
# by them, so renaming one is a breaking change.
BELOW_THRESHOLD = "below_threshold"
NO_FACE_DETECTED = "no_face_detected"
MULTIPLE_FACES = "multiple_faces"
LOW_QUALITY = "low_quality"
SUBJECT_NOT_ENROLLED = "subject_not_enrolled"
LIVENESS_FAILED = "liveness_failed"
MODEL_MISMATCH = "model_mismatch"


@dataclass(frozen=True, slots=True)
class Decision:
    """A completed verification, before it becomes a row or a response."""

    decision: str
    similarity: Decimal | None
    threshold: Decimal
    confidence: str | None
    failure_reason: str | None
    templates_compared: int
    quality: dict[str, Any] | None
    liveness: dict[str, Any] | None
    guidance: str | None
    detect_ms: int
    embed_ms: int
    match_ms: int

    @property
    def charges_quota(self) -> bool:
        """Everything except our own failures.

        An `inconclusive` *is* charged: we ran the models, it cost CPU, and the
        caller got an answer to act on. `error` is not, because the caller did
        nothing wrong and should not pay for our bug.
        """
        return self.decision != "error"


@dataclass(frozen=True, slots=True)
class QuotaState:
    used: int
    # `None` on Enterprise, where volume is a contract term rather than a number
    # this service enforces. Not the same as zero, and not the same as unlimited
    # by oversight.
    limit: int | None
    plan: str
    hard_stop: bool

    @property
    def exceeded(self) -> bool:
        return self.limit is not None and self.used >= self.limit

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else max(0, self.limit - self.used)

    @property
    def fraction(self) -> float:
        return self.used / self.limit if self.limit else 0.0


class VerificationService:
    def __init__(self, session: AsyncSession, actor: Actor, engine: FaceEngine) -> None:
        self.session = session
        self.actor = actor
        self.engine = engine
        self.subjects = SubjectRepository(session, actor.organization_id)
        self.profiles = FaceProfileRepository(session, actor.organization_id)
        self.templates = FaceTemplateRepository(session, actor.organization_id)

    # ── Entry point ───────────────────────────────────────────────────────────

    async def verify(
        self,
        *,
        subject_ref: str,
        image: str,
        requested_threshold: Decimal | None = None,
        require_liveness: bool | None = None,
        idempotency_key: str | None = None,
    ) -> VerificationSession:
        started = time.perf_counter()

        subject = await self._resolve(subject_ref)
        settings_row = await self._org_settings()

        applied = threshold_policy.resolve(
            configured=settings_row.match_threshold,
            requested=requested_threshold,
        )
        wants_liveness = (
            settings_row.require_liveness if require_liveness is None else require_liveness
        )

        profile = await self.profiles.get_active(subject.id)
        if profile is None:
            return await self._persist(
                subject=subject,
                decision=self._inconclusive(
                    applied,
                    SUBJECT_NOT_ENROLLED,
                    "This subject has no active face profile. Enroll them first.",
                ),
                started=started,
                idempotency_key=idempotency_key,
            )

        frame = await run_in_threadpool(lambda: decode_image(decode_base64(image)))

        decision = await run_in_threadpool(
            self._evaluate,
            frame,
            profile,
            await self._load_embeddings(profile.id),
            applied,
            wants_liveness,
        )

        return await self._persist(
            subject=subject,
            decision=decision,
            started=started,
            idempotency_key=idempotency_key,
        )

    # ── The CPU half ──────────────────────────────────────────────────────────

    def _evaluate(
        self,
        frame: np.ndarray[Any, Any],
        profile: FaceProfile,
        templates: list[Embedding],
        applied: Decimal,
        wants_liveness: bool,
    ) -> Decision:
        """Pure. No session, no I/O — runs whole in a worker thread."""
        model = self.engine.model
        if profile.model_name != model.name or profile.model_version != model.version:
            # Embeddings from different models are not comparable. Comparing
            # them anyway would not error, it would silently return garbage
            # similarities — which is exactly why this check exists rather than
            # being left to a deployment checklist.
            return self._inconclusive(
                applied,
                MODEL_MISMATCH,
                "This profile was created with a different model version and must be re-enrolled.",
            )

        if not templates:
            return self._inconclusive(
                applied,
                SUBJECT_NOT_ENROLLED,
                "This subject has no usable templates. Enroll them again.",
            )

        detect_started = time.perf_counter_ns()
        faces = self.engine.detect(frame)
        detect_ms = (time.perf_counter_ns() - detect_started) // 1_000_000

        if not faces:
            return self._inconclusive(
                applied, NO_FACE_DETECTED, "No face was found in the image.", detect_ms=detect_ms
            )
        if len(faces) > 1:
            return self._inconclusive(
                applied,
                MULTIPLE_FACES,
                "More than one face is visible. Capture one person at a time.",
                detect_ms=detect_ms,
            )

        face = faces[0]
        # Relaxed, not strict. Someone enrolling is cooperative and can retake;
        # someone authenticating at 11pm in a badly lit warehouse cannot.
        # Applying enrollment-grade strictness here produces a system that is
        # technically accurate and practically unusable.
        report = self.engine.assess_quality(frame, face, strict=False)
        quality = _quality_summary(report, face)

        failure = report.first_failure
        if failure is not None:
            return self._inconclusive(
                applied,
                LOW_QUALITY,
                GATE_GUIDANCE.get(failure.name, "Retake the photo."),
                detect_ms=detect_ms,
                quality=quality,
            )

        detector: LivenessDetector = (
            HeuristicLivenessDetector() if wants_liveness else DisabledLivenessDetector()
        )
        liveness: LivenessReport = detector.evaluate(frame, face)
        if liveness.evaluated and not liveness.passed:
            return self._inconclusive(
                applied,
                LIVENESS_FAILED,
                "The image looks like a photo of a screen or a print rather than a live face.",
                detect_ms=detect_ms,
                quality=quality,
                liveness=liveness.as_dict(),
            )

        embed_started = time.perf_counter_ns()
        probe = self.engine.embed(frame, face)
        embed_ms = (time.perf_counter_ns() - embed_started) // 1_000_000

        match_started = time.perf_counter_ns()
        _, score = best_match(probe, templates)
        match_ms = (time.perf_counter_ns() - match_started) // 1_000_000

        similarity = Decimal(str(round(score, 5)))
        verified = similarity >= applied

        return Decision(
            decision="verified" if verified else "rejected",
            similarity=similarity,
            threshold=applied,
            confidence=threshold_policy.confidence_for(similarity, applied),
            failure_reason=None if verified else BELOW_THRESHOLD,
            templates_compared=len(templates),
            quality=quality,
            liveness=liveness.as_dict() if liveness.evaluated else None,
            guidance=None,
            detect_ms=detect_ms,
            embed_ms=embed_ms,
            match_ms=match_ms,
        )

    # ── Quota ─────────────────────────────────────────────────────────────────

    async def quota_state(self) -> QuotaState:
        """Usage against the plan allowance for the current calendar month.

        Read from `usage_daily`, never by counting `verification_sessions`. The
        rollup is the difference between a check that stays constant-time and
        one that degrades as the busiest table in the system grows.
        """
        from sqlalchemy import func, select

        from app.modules.biometrics.models import UsageDaily

        organization = await self.session.get(Organization, self.actor.organization_id)
        plan = get_plan(organization.plan if organization else "free")

        month = datetime.now(tz=UTC).strftime("%Y-%m")
        used = await self.session.scalar(
            select(func.coalesce(func.sum(UsageDaily.count), 0)).where(
                UsageDaily.organization_id == self.actor.organization_id,
                UsageDaily.metric == "verifications",
                UsageDaily.day.startswith(month),
            )
        )

        return QuotaState(
            used=int(used or 0),
            limit=plan.monthly_verifications,
            plan=plan.name,
            hard_stop=plan.hard_stop_at_quota,
        )

    # ── Persistence ───────────────────────────────────────────────────────────

    async def _persist(
        self,
        *,
        subject: Subject,
        decision: Decision,
        started: float,
        idempotency_key: str | None,
    ) -> VerificationSession:
        now = datetime.now(tz=UTC)
        session_row = VerificationSession(
            organization_id=self.actor.organization_id,
            subject_id=subject.id,
            decision=decision.decision,
            similarity=decision.similarity,
            threshold_applied=decision.threshold,
            confidence=decision.confidence,
            failure_reason=decision.failure_reason,
            templates_compared=decision.templates_compared,
            quality_report=_report_payload(decision),
            latency_ms=int((time.perf_counter() - started) * 1000),
            detect_ms=decision.detect_ms,
            embed_ms=decision.embed_ms,
            match_ms=decision.match_ms,
            source=self.actor.source,
            ip_address=self.actor.ip_address,
            user_agent=self.actor.user_agent,
            idempotency_key=idempotency_key,
        )
        self.session.add(session_row)

        if decision.decision == "verified":
            subject.last_verified_at = now
            subject.verification_count += 1

        if decision.charges_quota:
            await self._record_usage(decision)

        await self.session.commit()

        # Queued after the commit, in its own transaction. Emitting inside the
        # decision's transaction would mean a webhook row could be rolled back
        # with a verification that actually happened - or worse, an event
        # promising an outcome the database never recorded.
        await self._emit_event(session_row, decision)

        logger.info(
            "verification_completed",
            verification_id=session_row.id,
            subject_id=subject.id,
            decision=decision.decision,
            similarity=float(decision.similarity) if decision.similarity is not None else None,
            threshold=float(decision.threshold),
            latency_ms=session_row.latency_ms,
        )
        return session_row

    async def _emit_event(self, row: VerificationSession, decision: Decision) -> None:
        """Queue `verification.completed` / `verification.failed` for delivery.

        Never raises into the request. A webhook subscription is a side channel;
        a customer's misconfigured endpoint must not be able to fail the
        verification that produced the event.
        """
        from app.modules.webhooks.service import WebhookService

        event = (
            "verification.completed" if decision.decision == "verified" else "verification.failed"
        )
        try:
            await WebhookService(self.session, self.actor.organization_id).emit(
                event,
                {
                    "verification_id": row.id,
                    "subject_id": row.subject_id,
                    "decision": row.decision,
                    "similarity": float(row.similarity) if row.similarity is not None else None,
                    "threshold": float(row.threshold_applied),
                    "confidence": row.confidence,
                    "failure_reason": row.failure_reason,
                    "created_at": row.created_at.isoformat(),
                },
            )
            await self.session.commit()
        except Exception as exc:
            logger.warning("webhook_emit_failed", verification_id=row.id, error=str(exc))
            await self.session.rollback()

    async def _record_usage(self, decision: Decision) -> None:
        """Increment today's rollup in place.

        An upsert rather than a read-modify-write: two concurrent verifications
        would otherwise both read the same count and one increment would be
        lost. At the volumes this table sees, that is not hypothetical.
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        from app.modules.biometrics.models import UsageDaily

        # Both dialects spell it `on_conflict_do_update`, but the constructs come
        # from different modules and are not interchangeable.
        dialect = self.session.bind.dialect.name if self.session.bind else "postgresql"
        insert = pg_insert if dialect == "postgresql" else sqlite_insert

        success = 1 if decision.decision == "verified" else 0
        rejected = 1 if decision.decision == "rejected" else 0
        inconclusive = 1 if decision.decision == "inconclusive" else 0

        # `id` is omitted deliberately: a Core insert() applies the ORM's
        # Python-side column default for any column absent from values(),
        # verified rather than assumed.
        statement = insert(UsageDaily).values(
            organization_id=self.actor.organization_id,
            day=datetime.now(tz=UTC).strftime("%Y-%m-%d"),
            metric="verifications",
            count=1,
            success_count=success,
            rejected_count=rejected,
            inconclusive_count=inconclusive,
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["organization_id", "day", "metric"],
                set_={
                    "count": UsageDaily.count + 1,
                    "success_count": UsageDaily.success_count + success,
                    "rejected_count": UsageDaily.rejected_count + rejected,
                    "inconclusive_count": UsageDaily.inconclusive_count + inconclusive,
                },
            )
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _resolve(self, identifier: str) -> Subject:
        from app.modules.biometrics.service import EXTERNAL_ID_PREFIX

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

    async def _load_embeddings(self, face_profile_id: str) -> list[Embedding]:
        rows = await self.templates.list_for_profile(face_profile_id)
        return [np.asarray(row.embedding, dtype=np.float32).ravel() for row in rows]

    async def _org_settings(self) -> OrgSettings:
        row = await self.session.get(OrgSettings, self.actor.organization_id)
        if row is None:
            raise NotFoundError("Organization settings not found.")
        return row

    @staticmethod
    def _inconclusive(
        applied: Decimal,
        reason: str,
        guidance: str,
        *,
        detect_ms: int = 0,
        quality: dict[str, Any] | None = None,
        liveness: dict[str, Any] | None = None,
    ) -> Decision:
        return Decision(
            decision="inconclusive",
            similarity=None,
            threshold=applied,
            confidence=None,
            failure_reason=reason,
            templates_compared=0,
            quality=quality,
            liveness=liveness,
            guidance=guidance,
            detect_ms=detect_ms,
            embed_ms=0,
            match_ms=0,
        )


def _quality_summary(report: Any, face: Any) -> dict[str, Any]:
    """The quality numbers a caller can act on, not the whole gate dump."""
    values = {gate.name: gate.value for gate in report.gates}
    return {
        "score": round(report.score, 3),
        "sharpness": round(values.get("sharpness", 0.0), 3),
        "brightness": round(values.get("brightness", 0.0), 3),
        "face_size_px": round(face.inter_ocular_px, 1),
        "pose": {
            "yaw": round(face.pose.yaw, 2),
            "pitch": round(face.pose.pitch, 2),
            "roll": round(face.pose.roll, 2),
        },
        "checks": [gate.as_dict() for gate in report.gates],
    }


def _report_payload(decision: Decision) -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    if decision.quality:
        payload["quality"] = decision.quality
    if decision.liveness:
        payload["liveness"] = decision.liveness
    if decision.guidance:
        payload["guidance"] = decision.guidance
    return payload or None
