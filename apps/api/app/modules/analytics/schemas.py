"""Analytics and log contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.shared.schemas import Page, Pagination


class MetricDelta(BaseModel):
    """A value with its change against the immediately preceding period.

    The delta is what turns a number into information: "12,481 verifications"
    says little; "12,481, up 12.4%" says whether to act.
    """

    value: float
    previous: float
    change_pct: float | None
    # Whether an increase is good. Latency going up is bad; volume going up is
    # not — the client cannot know which without being told.
    higher_is_better: bool


class OverviewResponse(BaseModel):
    verifications: MetricDelta
    success_rate: MetricDelta
    p95_latency_ms: MetricDelta
    active_subjects: MetricDelta
    period_days: int
    # Distinguishes "never had data" from "no data in this range" — two states
    # that need different empty screens.
    has_any_data: bool


class TimeseriesPoint(BaseModel):
    day: str
    verified: int
    rejected: int
    inconclusive: int
    total: int


class OutcomeSlice(BaseModel):
    decision: str
    count: int
    percentage: float


class FailureReason(BaseModel):
    reason: str
    count: int
    percentage: float


class LatencyBucket(BaseModel):
    bucket: str
    count: int


class LatencyDistribution(BaseModel):
    buckets: list[LatencyBucket]
    p50: int
    p95: int
    p99: int


class HourlyCell(BaseModel):
    weekday: int
    hour: int
    total: int
    success_rate: float | None


class UsageResponse(BaseModel):
    plan: str
    used: int
    limit: int | None
    percentage: float
    period_start: str
    period_end: str
    days_remaining: int
    remaining: int | None
    # Free hard-stops at quota; paid plans keep serving and bill the overage.
    # The console needs this to say which one will happen, rather than showing
    # an identical bar for two very different outcomes.
    hard_stop: bool


class AuditLogEntry(BaseModel):
    id: str
    actor_type: str
    actor_email: str | None
    action: str
    resource_type: str
    resource_id: str | None
    changes: dict[str, Any] | None
    ip_address: str | None
    request_id: str | None
    created_at: datetime


class AuthLogEntry(BaseModel):
    id: str
    email: str | None
    event: str
    success: bool
    ip_address: str | None
    user_agent: str | None
    detail: str | None
    created_at: datetime


class VerificationListItem(BaseModel):
    id: str
    subject_id: str | None
    subject_external_id: str | None
    decision: str
    similarity: float | None
    threshold_applied: float
    confidence: str | None
    failure_reason: str | None
    latency_ms: int
    source: str
    created_at: datetime


class SubjectListItem(BaseModel):
    id: str
    external_id: str
    display_name: str | None
    status: str
    verification_count: int
    enrolled_at: datetime | None
    last_verified_at: datetime | None
    created_at: datetime


# Re-exported, not redefined. The envelope is identical for every list endpoint
# in the product, so it lives in app.shared.schemas; this import keeps existing
# call sites working without giving analytics ownership of a cross-cutting type.
__all__ = ["Page", "Pagination"]


# ── Threshold simulation ──────────────────────────────────────────────────────


class SimulatedFlip(BaseModel):
    """A session whose outcome the candidate threshold would change."""

    id: str
    subject_id: str | None
    subject_external_id: str | None
    similarity: float
    original_decision: str
    simulated_decision: str
    confidence: str | None
    created_at: datetime


class SimilarityBucket(BaseModel):
    from_: float = Field(alias="from")
    to: float
    count: int

    model_config = {"populate_by_name": True}


class ThresholdSimulation(BaseModel):
    """What a candidate threshold would have done to real traffic.

    Counts cover the whole window; `examples` is a bounded sample ordered by how
    marginal each decision was, because the rows nearest the threshold are the
    ones worth a human's attention.
    """

    current_threshold: float
    candidate_threshold: float
    window_days: int

    comparable: int = Field(
        description=(
            "Sessions a threshold could have moved. Excludes `inconclusive` — the "
            "pipeline stopped before matching, so no threshold would change them."
        )
    )
    unchanged: int

    original_verified: int
    original_rejected: int
    simulated_verified: int
    simulated_rejected: int

    newly_rejected: int = Field(
        description="Accepted before, rejected now. A usability cost paid by real users."
    )
    newly_accepted: int = Field(description="Rejected before, accepted now. A security cost.")

    acceptance_rate_before: float
    acceptance_rate_after: float

    examples: list[SimulatedFlip] = Field(default_factory=list)
    histogram: list[SimilarityBucket] = Field(default_factory=list)
