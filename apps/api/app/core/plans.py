"""Plan limits.

In code rather than in a table, deliberately. These are *product* definitions:
they change when pricing changes, they must be identical across every
environment, and a plan row that drifted in one database would mean a customer
silently getting a different quota than the pricing page promises. A migration
is the right way to change them, not an UPDATE.

The numbers mirror [docs/01-prd.md §9](../../../docs/01-prd.md). If the two
disagree, the pricing page is the contract and this file is the bug.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class Plan:
    name: str
    # `None` means negotiated, not unlimited-by-accident. Enterprise volume is
    # a contract term, so enforcing a number nobody agreed to would be worse
    # than enforcing nothing here and billing from the contract.
    monthly_verifications: int | None
    max_subjects: int | None
    max_members: int | None
    log_retention_days: int
    webhooks_enabled: bool
    custom_threshold: bool
    # Free hard-stops at quota; paid plans keep serving and bill the overage.
    # Breaking a paying customer's login flow over a billing event would be a
    # far worse failure than an unexpected invoice line (docs/01-prd.md §9).
    hard_stop_at_quota: bool
    # Per-second token bucket on the verification endpoint.
    verifications_per_second: int
    enrollments_per_second: int
    reads_per_second: int


FREE: Final = Plan(
    name="free",
    monthly_verifications=1_000,
    max_subjects=500,
    max_members=2,
    log_retention_days=7,
    webhooks_enabled=False,
    custom_threshold=False,
    hard_stop_at_quota=True,
    verifications_per_second=10,
    enrollments_per_second=2,
    reads_per_second=20,
)

STARTUP: Final = Plan(
    name="startup",
    monthly_verifications=25_000,
    max_subjects=10_000,
    max_members=5,
    log_retention_days=30,
    webhooks_enabled=True,
    custom_threshold=False,
    hard_stop_at_quota=False,
    verifications_per_second=50,
    enrollments_per_second=10,
    reads_per_second=100,
)

GROWTH: Final = Plan(
    name="growth",
    monthly_verifications=150_000,
    max_subjects=None,
    max_members=20,
    log_retention_days=90,
    webhooks_enabled=True,
    custom_threshold=True,
    hard_stop_at_quota=False,
    verifications_per_second=200,
    enrollments_per_second=50,
    reads_per_second=300,
)

ENTERPRISE: Final = Plan(
    name="enterprise",
    monthly_verifications=None,
    max_subjects=None,
    max_members=None,
    log_retention_days=365,
    webhooks_enabled=True,
    custom_threshold=True,
    hard_stop_at_quota=False,
    verifications_per_second=500,
    enrollments_per_second=100,
    reads_per_second=1_000,
)

PLANS: Final[dict[str, Plan]] = {plan.name: plan for plan in (FREE, STARTUP, GROWTH, ENTERPRISE)}

# Thresholds at which a quota notification fires, as a fraction of the monthly
# allowance. Crossing is edge-triggered — a customer at 92% must not be emailed
# on every request for the rest of the month (docs/01-prd.md FR-5.5).
QUOTA_NOTIFY_AT: Final[tuple[float, ...]] = (0.8, 1.0)


def get_plan(name: str) -> Plan:
    """Look up a plan, falling back to Free.

    Falling back rather than raising: an unrecognised plan name is a data
    problem, and the safe response is the *most* restrictive plan, not a crash
    on the verification hot path.
    """
    return PLANS.get(name, FREE)
