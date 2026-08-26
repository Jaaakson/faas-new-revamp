"""Subjects, face profiles, templates, and verification sessions.

Phase 4 added the analytics-facing tables; Phase 5 adds the biometric ones now
that there is code to write to them and tests to prove their deletion
guarantees.

Two properties here are not negotiable and are enforced structurally rather
than by convention:

* **`face_templates` has no `deleted_at`.** Deletion is physical. A
  soft-deleted biometric template is still retained biometric data.
* **One active `face_profile` per subject**, enforced by a partial unique
  index. Two active profiles would make verification non-deterministic.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import (
    Base,
    IDMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UTCDateTime,
)
from app.shared.utils import ids
from app.shared.vector_type import Embedding

# JSONB on PostgreSQL, plain JSON elsewhere. The blueprint specifies JSONB
# (docs/06-database.md §4.3) — binary storage, and the only form that a GIN
# index can be added to if filtering demand appears. The variant keeps the
# SQLite-backed test suite working without a second model definition.
JsonColumn = JSON().with_variant(JSONB(), "postgresql")

SUBJECT_STATUSES = ("pending", "enrolled", "suspended")
DECISIONS = ("verified", "rejected", "inconclusive", "error")

FAILURE_REASONS = (
    "below_threshold",
    "no_face_detected",
    "multiple_faces",
    "low_quality",
    "subject_not_enrolled",
    "liveness_failed",
    "model_mismatch",
)


class Subject(Base, IDMixin, TimestampMixin, SoftDeleteMixin):
    """One of the customer's end users — the person whose face gets verified.

    Not a `User`. See docs/06-database.md §3: different scale, different auth,
    different lifecycle, different deletion obligations.
    """

    __id_prefix__ = ids.SUBJECT

    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # The customer's own identifier, so nothing in their database has to change.
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Customer-defined. JSON rather than typed columns because the shape is
    # theirs, not ours. No GIN index until filtering demand actually appears —
    # indexing speculatively costs write throughput on the busiest table.
    subject_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JsonColumn,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )

    # The customer's proof-of-consent record. They are the controller; this
    # field makes that boundary explicit rather than implied.
    consent_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    consent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    enrolled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # Denormalised counter. Updated at most once a minute via a coalesced write
    # (docs/06-database.md §6) — a row update per verification would create lock
    # contention on the hottest path in the system.
    verification_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'enrolled', 'suspended')", name="ck_subjects_status"
        ),
        # Partial on `deleted_at IS NULL`. Deleting a subject soft-deletes this
        # row for audit continuity while physically destroying the templates
        # (docs/09-security.md §5), and the customer must then be able to
        # re-onboard the same person under the same external_id. A plain unique
        # index would make deletion permanently poison that identifier.
        Index(
            "uq_subjects_org_external",
            "organization_id",
            "external_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_subjects_org_status", "organization_id", "status", "created_at"),
    )


class VerificationSession(Base, IDMixin, TimestampMixin):
    """One verification attempt and its evidence.

    The highest-volume table in the system. Every attempt is stored, including
    failures — failure rates are a product signal, not noise.
    """

    __id_prefix__ = ids.VERIFICATION_SESSION

    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Nullable: the caller may reference a subject that does not exist, and that
    # attempt still belongs in the log.
    subject_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True
    )

    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    similarity: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), nullable=True)
    # Denormalised on purpose: an auditor asking why something was verified in
    # March must get March's threshold, not today's configuration.
    threshold_applied: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    templates_compared: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    quality_report: Mapped[dict[str, Any] | None] = mapped_column(JsonColumn, nullable=True)

    latency_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    detect_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    match_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="api", server_default="api"
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "decision IN ('verified', 'rejected', 'inconclusive', 'error')",
            name="ck_verification_sessions_decision",
        ),
        # The default list view. Leading with organization_id is what makes the
        # tenant filter index-friendly rather than a scan-and-discard.
        Index("ix_verifications_org_created", "organization_id", "created_at"),
        Index("ix_verifications_org_decision", "organization_id", "decision", "created_at"),
        Index("ix_verifications_org_subject", "organization_id", "subject_id", "created_at"),
        # Partial: only rows that actually carry a key participate, so the many
        # requests without one do not collide on NULL.
        Index(
            "uq_verifications_idempotency",
            "organization_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
            sqlite_where=text("idempotency_key IS NOT NULL"),
        ),
    )


class UsageDaily(Base, IDMixin, TimestampMixin):
    """Pre-aggregated daily metrics.

    Analytics reads from here, never from `verification_sessions`. This is the
    difference between a dashboard that stays fast at 10M rows and one that
    times out at 500K (docs/06-database.md §6).
    """

    __tablename__ = "usage_daily"

    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Stored as a date-only string so the rollup key is unambiguous across
    # timezones and trivially groupable in SQL on either backend.
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    metric: Mapped[str] = mapped_column(String(24), nullable=False)

    count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    success_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    rejected_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    inconclusive_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    p95_latency_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    __table_args__ = (
        Index("uq_usage_daily", "organization_id", "day", "metric", unique=True),
        Index("ix_usage_daily_org_day", "organization_id", "day"),
    )


class AuditLog(Base, IDMixin, TimestampMixin):
    """Every mutating action, append-only.

    Written in the same transaction as the change it records, so a committed
    change without its audit entry is not representable. The application's
    database role has no UPDATE or DELETE grant on this table — an audit log the
    application can rewrite proves nothing (docs/09-security.md §6).
    """

    __id_prefix__ = ids.AUDIT_LOG

    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    actor_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="user", server_default="user"
    )
    actor_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Before/after, with sensitive fields already redacted by the service.
    changes: Mapped[dict[str, Any] | None] = mapped_column(JsonColumn, nullable=True)

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(48), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('user', 'api_key', 'system')", name="ck_audit_logs_actor_type"
        ),
        Index("ix_audit_logs_org_created", "organization_id", "created_at"),
        Index("ix_audit_logs_org_action", "organization_id", "action", "created_at"),
        Index("ix_audit_logs_resource", "organization_id", "resource_type", "resource_id"),
    )


class FaceProfile(Base, IDMixin, TimestampMixin):
    """A versioned enrollment for one subject.

    Re-enrolling creates a new version and supersedes the previous one rather
    than overwriting it, so a verification decision made last March can still be
    explained by the profile that was active then.
    """

    __id_prefix__ = ids.FACE_PROFILE

    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )

    # Embeddings from different models are not comparable. Recording which model
    # produced a template turns a silent accuracy collapse after an upgrade into
    # a detectable `model_mismatch` (docs/08-ai-workflow.md §7).
    model_name: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    embedding_dim: Mapped[int] = mapped_column(
        Integer, nullable=False, default=512, server_default=text("512")
    )

    template_count: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_quality_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)

    enrolled_by_user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    templates: Mapped[list[FaceTemplate]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'superseded', 'revoked')", name="ck_face_profiles_status"
        ),
        # One active profile per subject, enforced by the database rather than
        # by service discipline. A subject with two active profiles would make
        # verification non-deterministic.
        Index(
            "uq_face_profiles_active_subject",
            "subject_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index("ix_face_profiles_org_subject", "organization_id", "subject_id"),
    )


class FaceTemplate(Base, IDMixin, TimestampMixin):
    """One biometric template — a 512-d embedding of a single capture.

    **No `deleted_at`.** Deletion here is physical. A soft-deleted biometric
    template is still retained biometric data, which is exactly what a deletion
    request forbids (docs/06-database.md §4.3, docs/09-security.md §4).
    """

    __id_prefix__ = ids.FACE_TEMPLATE

    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    face_profile_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("face_profiles.id", ondelete="CASCADE"), nullable=False
    )

    # vector(512) on Postgres, float32 bytes on SQLite. L2-normalised at write,
    # so cosine similarity is a dot product.
    embedding: Mapped[Any] = mapped_column(Embedding, nullable=False)

    quality_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    sharpness: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    brightness: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    pose_yaw: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    pose_pitch: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    pose_roll: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    bbox: Mapped[dict[str, Any] | None] = mapped_column(JsonColumn, nullable=True)

    # Only populated when the organization explicitly opts into retention.
    # Null is the default and the overwhelmingly common case.
    image_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    profile: Mapped[FaceProfile] = relationship(back_populates="templates")

    __table_args__ = (
        Index("ix_face_templates_profile", "face_profile_id"),
        Index("ix_face_templates_org", "organization_id"),
        # Declared here so the model stays the single source of truth and
        # `alembic check` does not propose dropping it. The postgresql_* options
        # are ignored on other backends, where it degrades to an unused index on
        # the blob column — harmless, and only the test suite ever sees it.
        Index(
            "ix_face_templates_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class EnrollmentAttempt(Base, IDMixin, TimestampMixin):
    """Every enrollment attempt, including failures.

    Failure rates are a product signal — they say whether the capture UI is
    working — so a rejected enrollment is recorded just as carefully as a
    successful one.
    """

    __id_prefix__ = ids.ENROLLMENT

    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True
    )
    face_profile_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("face_profiles.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[str] = mapped_column(String(24), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    image_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    accepted_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # Per-image gate outcomes. An integrator building a capture UI needs to know
    # *which* frame was weak, not just that one was.
    quality_report: Mapped[dict[str, Any] | None] = mapped_column(JsonColumn, nullable=True)

    duplicate_subject_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duplicate_similarity: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), nullable=True)

    enrolled_by_user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="api", server_default="api"
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latency_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'failed', 'duplicate_detected')",
            name="ck_enrollment_attempts_status",
        ),
        Index("ix_enrollments_org_created", "organization_id", "created_at"),
        Index("ix_enrollments_org_subject", "organization_id", "subject_id", "created_at"),
    )


class AuditAction:
    """Action names. Constants, not free text — these are queried and filtered."""

    ORGANIZATION_UPDATED = "organization.updated"
    SETTINGS_UPDATED = "settings.updated"
    THRESHOLD_UPDATED = "threshold.updated"
    MEMBER_INVITED = "member.invited"
    MEMBER_ROLE_CHANGED = "member.role_changed"
    MEMBER_REMOVED = "member.removed"
    INVITATION_REVOKED = "invitation.revoked"
    SUBJECT_CREATED = "subject.created"
    SUBJECT_DELETED = "subject.deleted"
    ENROLLMENT_COMPLETED = "enrollment.completed"
    ENROLLMENT_DUPLICATE = "enrollment.duplicate_detected"
    FACE_PROFILE_REVOKED = "face_profile.revoked"
    FACE_PROFILE_SUPERSEDED = "face_profile.superseded"
    APIKEY_CREATED = "apikey.created"
    APIKEY_REVOKED = "apikey.revoked"


# ── Webhooks ──────────────────────────────────────────────────────────────────

WEBHOOK_EVENTS = (
    "verification.completed",
    "verification.failed",
    "enrollment.completed",
    "enrollment.duplicate_detected",
    "subject.deleted",
    "quota.threshold_reached",
)

DELIVERY_STATUSES = ("pending", "delivered", "failed")

# Consecutive failures before an endpoint is switched off. Twenty attempts is
# roughly a day of retries; past that the endpoint is not "temporarily down",
# it is gone, and continuing to retry costs us a worker and them nothing.
MAX_CONSECUTIVE_FAILURES = 20


class WebhookEndpoint(Base, IDMixin, TimestampMixin, SoftDeleteMixin):
    """A customer URL that receives events."""

    __id_prefix__ = ids.WEBHOOK_ENDPOINT

    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Which events this endpoint wants. JSON rather than a join table: the list
    # is short, always read whole, and never queried across endpoints.
    events: Mapped[list[str]] = mapped_column(
        JsonColumn, nullable=False, default=list, server_default=text("'[]'")
    )

    # Per-endpoint, not per-organization. Rotating one customer integration's
    # secret must not invalidate signatures for all the others.
    secret: Mapped[str] = mapped_column(String(128), nullable=False)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # Reset to zero on any success — this counts *consecutive* failures, so a
    # flaky endpoint that mostly works is never disabled.
    failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    disabled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_delivery_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    __table_args__ = (Index("ix_webhook_endpoints_org", "organization_id", "is_active"),)


class WebhookDelivery(Base, IDMixin, TimestampMixin):
    """One attempt to deliver one event.

    Kept even after success, because "did you send it?" is the first question in
    every webhook support thread and an answer of "probably" is worthless.
    """

    __id_prefix__ = ids.WEBHOOK_DELIVERY

    organization_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    endpoint_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False
    )

    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    # The receiver dedupes on this. Delivery is at-least-once, and saying so
    # loudly is more honest than implying exactly-once and failing at it.
    event_id: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonColumn, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Truncated. A customer returning a 2 MB HTML error page must not be able to
    # fill our database with it.
    response_body: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'delivered', 'failed')",
            name="ck_webhook_deliveries_status",
        ),
        Index("ix_webhook_deliveries_org_created", "organization_id", "created_at"),
        Index("ix_webhook_deliveries_endpoint", "endpoint_id", "created_at"),
        # The worker's claim query: due, not yet given up on. Partial so the
        # index stays small as delivered rows accumulate — they are the vast
        # majority and none of them are ever scanned by the worker.
        Index(
            "ix_webhook_deliveries_due",
            "next_retry_at",
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )
