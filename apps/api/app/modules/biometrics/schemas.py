"""Subject and enrollment contracts.

Two shapes deserve explanation.

**Per-image results are returned even on success.** An integrator building a
capture UI needs to know *which* frame was weak in order to coach their user;
a bare `"status": "succeeded"` forces them to guess (docs/07-api-design.md §3.2).

**Failures carry a reason code and human guidance side by side.** The code is
for the integrator's `switch`, the guidance is for their end user. Returning
only one of the two makes every integration either brittle or unhelpful.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings


class SubjectCreate(BaseModel):
    external_id: str = Field(
        min_length=1,
        max_length=128,
        description="Your own identifier for this person. Unique within your organization.",
        examples=["user_84213"],
    )
    display_name: str | None = Field(default=None, max_length=120)
    consent_reference: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "Your proof-of-consent record. Required when consent enforcement is on: "
            "you are the data controller, and this makes that boundary explicit."
        ),
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("external_id")
    @classmethod
    def _no_surrounding_space(cls, value: str) -> str:
        # A trailing space is invisible in a dashboard and would create a second,
        # apparently identical subject.
        stripped = value.strip()
        if not stripped:
            raise ValueError("external_id cannot be blank")
        return stripped

    @field_validator("metadata")
    @classmethod
    def _bounded_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        # The shape is the customer's, but the size is ours to bound — this
        # column is on the highest-volume table in the system.
        if len(value) > 50:
            raise ValueError("metadata is limited to 50 keys")
        return value


class SubjectUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    status: str | None = Field(default=None, description="`pending`, `enrolled` or `suspended`")
    consent_reference: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] | None = None

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: str | None) -> str | None:
        # `enrolled` is not settable: it is a statement about whether biometric
        # data exists, and only the enrollment pipeline can make it true.
        if value is not None and value not in {"pending", "suspended"}:
            raise ValueError("status must be 'pending' or 'suspended'")
        return value


class ModelRef(BaseModel):
    name: str
    version: str


class FaceProfileResponse(BaseModel):
    id: str
    version: int
    status: str
    template_count: int
    avg_quality_score: float | None
    model: ModelRef
    created_at: datetime
    superseded_at: datetime | None = None
    revoked_at: datetime | None = None


class SubjectResponse(BaseModel):
    id: str
    external_id: str
    display_name: str | None
    status: str
    consent_reference: str | None
    metadata: dict[str, Any]
    verification_count: int
    enrolled_at: datetime | None
    last_verified_at: datetime | None
    created_at: datetime


class SubjectDetail(SubjectResponse):
    """Adds the enrollment state a detail page needs in one round trip."""

    face_profile: FaceProfileResponse | None = None
    profile_history: list[FaceProfileResponse] = Field(default_factory=list)


class EnrollmentOptions(BaseModel):
    check_duplicates: bool | None = Field(
        default=None,
        description=(
            "Search existing enrolled faces before creating the profile. "
            "Defaults to the organization setting."
        ),
    )
    min_quality: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Reject frames scoring below this, on top of the standard gates.",
    )
    replace_existing: bool = Field(
        default=True,
        description=(
            "Supersede an existing active profile. With `false`, enrolling a subject "
            "that already has one is a 409 rather than a silent replacement."
        ),
    )


class EnrollmentRequest(BaseModel):
    subject_id: str = Field(
        description="A subject id, or `ext_<your external id>`.",
        examples=["sub_01HQZX8K4M2N7P", "ext_user_84213"],
    )
    images: list[str] = Field(
        min_length=1,
        description="Base64-encoded JPEG/PNG/WebP frames. A `data:` URL is accepted.",
    )
    options: EnrollmentOptions = Field(default_factory=EnrollmentOptions)

    @field_validator("images")
    @classmethod
    def _bounded_image_count(cls, value: list[str]) -> list[str]:
        # Enforced here as well as in the service so an oversized batch is
        # rejected before any of it is base64-decoded into memory.
        if len(value) > settings.MAX_ENROLLMENT_IMAGES:
            raise ValueError(
                f"at most {settings.MAX_ENROLLMENT_IMAGES} images may be submitted per enrollment"
            )
        return value


class GateCheck(BaseModel):
    check: str
    passed: bool
    score: float
    value: float
    required: float


class EnrollmentImageResult(BaseModel):
    index: int
    accepted: bool
    quality_score: float
    reason: str | None = None
    guidance: str | None = None
    checks: list[GateCheck] = Field(default_factory=list)
    bbox: dict[str, float] | None = None


class EnrollmentResponse(BaseModel):
    id: str
    status: str = Field(description="`succeeded`, `failed` or `duplicate_detected`")
    subject_id: str | None
    face_profile: FaceProfileResponse | None = None
    images: list[EnrollmentImageResult] = Field(default_factory=list)
    failure_reason: str | None = None
    latency_ms: int
    created_at: datetime


class EnrollmentListItem(BaseModel):
    id: str
    subject_id: str | None
    subject_external_id: str | None = None
    status: str
    failure_reason: str | None
    image_count: int
    accepted_count: int
    duplicate_subject_id: str | None
    latency_ms: int
    source: str
    created_at: datetime


class EnrollmentDetail(EnrollmentListItem):
    face_profile_id: str | None
    duplicate_similarity: float | None
    images: list[EnrollmentImageResult] = Field(default_factory=list)
    enrolled_by_user_id: str | None


# ── Verification ──────────────────────────────────────────────────────────────


class VerificationOptions(BaseModel):
    threshold: Decimal | None = Field(
        default=None,
        gt=0,
        lt=1,
        description=(
            "Match threshold for this request. May only be **stricter** than your "
            "organization's setting - a looser value is silently raised to it, so a "
            "compromised key cannot weaken your security posture."
        ),
    )
    require_liveness: bool | None = Field(
        default=None,
        description="Override the organization's liveness setting for this request.",
    )


class VerificationRequest(BaseModel):
    subject_id: str = Field(
        description="A subject id, or `ext_<your external id>`.",
        examples=["sub_01HQZX8K4M2N7P", "ext_user_84213"],
    )
    image: str = Field(description="Base64-encoded JPEG/PNG/WebP. A `data:` URL is accepted.")
    options: VerificationOptions = Field(default_factory=VerificationOptions)


class PoseSummary(BaseModel):
    yaw: float
    pitch: float
    roll: float


class QualitySummary(BaseModel):
    score: float
    sharpness: float
    brightness: float
    face_size_px: float
    pose: PoseSummary
    checks: list[GateCheck] = Field(default_factory=list)


class LivenessSignalOut(BaseModel):
    signal: str
    score: float
    passed: bool
    required: float


class LivenessSummary(BaseModel):
    evaluated: bool
    passed: bool
    score: float
    signals: list[LivenessSignalOut] = Field(default_factory=list)


class TimingBreakdown(BaseModel):
    total_ms: int
    detect_ms: int | None = None
    embed_ms: int | None = None
    match_ms: int | None = None


class VerificationResponse(BaseModel):
    id: str
    decision: str = Field(
        description=(
            "`verified` - similarity at or above threshold. "
            "`rejected` - a real face, but not this person. "
            "`inconclusive` - could not decide (no face, poor quality, liveness, not enrolled). "
            "`error` - our failure, not charged against your quota."
        )
    )
    subject_id: str | None
    similarity: float | None
    threshold: float
    confidence: str | None
    failure_reason: str | None
    guidance: str | None = None
    templates_compared: int
    quality: QualitySummary | None = None
    liveness: LivenessSummary | None = None
    timing: TimingBreakdown
    created_at: datetime


class VerificationListItem(BaseModel):
    id: str
    subject_id: str | None
    subject_external_id: str | None = None
    decision: str
    similarity: float | None
    threshold_applied: float
    confidence: str | None
    failure_reason: str | None
    latency_ms: int
    source: str
    created_at: datetime


class VerificationDetail(VerificationListItem):
    templates_compared: int
    detect_ms: int | None
    embed_ms: int | None
    match_ms: int | None
    ip_address: str | None
    user_agent: str | None
    quality: QualitySummary | None = None
    liveness: LivenessSummary | None = None


class QuotaResponse(BaseModel):
    plan: str
    used: int
    limit: int
    remaining: int
    percent_used: float
    hard_stop: bool
    period: str


class ThresholdInfo(BaseModel):
    """What the console shows beside the threshold control.

    `measured` is the honest field: a custom threshold has no calibrated FAR/FRR,
    and printing a reassuring zero would be worse than printing nothing.
    """

    preset: str
    threshold: float
    far: float | None
    frr: float | None
    measured: bool
    intent: str | None = None
    note: str | None = None
