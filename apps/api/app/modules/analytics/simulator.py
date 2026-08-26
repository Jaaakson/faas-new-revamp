"""Threshold simulation over recorded verification history.

Answers the question the threshold slider cannot: **what would this have done to
my traffic?**

Every ingredient is already stored. `verification_sessions` keeps the
`similarity` that was computed and the `threshold_applied` at the time, so a
candidate threshold can be replayed against real decisions without re-running a
single inference.

That matters more here than it would in most products. The published FAR/FRR
figures come from LFW, and [the model card](../../../../docs/16-model-card.md)
is explicit that LFW is easier than production and that those numbers are an
upper bound for any population unlike it. This gives a customer *their* numbers
instead of a benchmark's.

Two boundaries are deliberate:

* **Only `verified` and `rejected` rows are replayed.** An `inconclusive` had no
  similarity to compare — the pipeline stopped before matching — so no threshold
  would have changed it. Counting them would inflate the denominator and make
  the simulation look more decisive than it is.
* **`error` rows are excluded** for the same reason they are excluded from
  billing: they are ours, not a customer outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.biometrics.models import Subject, VerificationSession

# The decisions a threshold can actually move. See the module docstring.
COMPARABLE_DECISIONS = ("verified", "rejected")

# Cap on the worked examples returned alongside the counts. The counts come from
# aggregate SQL over the whole window; this is the "show me" list, and a customer
# scrolling 4,000 flipped rows is not making a better decision than one reading
# 50.
MAX_EXAMPLES = 50


@dataclass(frozen=True, slots=True)
class Flip:
    """One session whose outcome the candidate threshold would change."""

    id: str
    subject_id: str | None
    subject_external_id: str | None
    similarity: float
    original_decision: str
    simulated_decision: str
    confidence: str | None
    created_at: datetime


@dataclass
class SimulationResult:
    current_threshold: float
    candidate_threshold: float
    window_days: int

    comparable: int = 0
    original_verified: int = 0
    original_rejected: int = 0
    simulated_verified: int = 0
    simulated_rejected: int = 0

    # Directional, because they mean opposite things. Newly rejected is a
    # usability cost paid by real users; newly accepted is a security cost.
    newly_rejected: int = 0
    newly_accepted: int = 0

    examples: list[Flip] = field(default_factory=list)
    # Similarity distribution, so the UI can draw where the threshold sits
    # relative to the mass of real traffic rather than on an empty axis.
    histogram: list[dict[str, float]] = field(default_factory=list)

    @property
    def unchanged(self) -> int:
        return self.comparable - self.newly_rejected - self.newly_accepted

    @property
    def acceptance_rate_before(self) -> float:
        return self.original_verified / self.comparable if self.comparable else 0.0

    @property
    def acceptance_rate_after(self) -> float:
        return self.simulated_verified / self.comparable if self.comparable else 0.0


class ThresholdSimulator:
    """Replays stored similarities against a candidate threshold."""

    def __init__(self, session: AsyncSession, organization_id: str) -> None:
        self.session = session
        self.organization_id = organization_id

    def _scope(self, since: datetime) -> Select[tuple[VerificationSession]]:
        return select(VerificationSession).where(
            VerificationSession.organization_id == self.organization_id,
            VerificationSession.decision.in_(COMPARABLE_DECISIONS),
            VerificationSession.similarity.is_not(None),
            VerificationSession.created_at >= since,
        )

    async def run(
        self,
        *,
        candidate: Decimal,
        current: Decimal,
        days: int = 30,
    ) -> SimulationResult:
        since = datetime.now(tz=UTC) - timedelta(days=days)
        result = SimulationResult(
            current_threshold=float(current),
            candidate_threshold=float(candidate),
            window_days=days,
        )

        # Counts come from aggregate SQL, not from loading rows into Python. A
        # tenant with a year of traffic has millions of sessions, and the whole
        # point of this feature is that it stays instant enough to drag a slider.
        #
        # Every predicate below references `rows.c.*`, the *subquery's* columns —
        # never the mapped class. Referencing `VerificationSession` here would
        # add the base table to the FROM clause a second time and silently
        # produce a cross join: with three sessions the counts came back as nine.
        # Aggregates over a cartesian product still look like plausible numbers,
        # which is exactly what makes the mistake dangerous.
        rows = self._scope(since).subquery()
        totals = (
            await self.session.execute(
                select(
                    func.count().label("comparable"),
                    func.count().filter(rows.c.decision == "verified").label("verified"),
                    func.count().filter(rows.c.decision == "rejected").label("rejected"),
                    # Would have been accepted under the candidate.
                    func.count().filter(rows.c.similarity >= candidate).label("sim_verified"),
                    # Accepted before, rejected now.
                    func.count()
                    .filter(and_(rows.c.decision == "verified", rows.c.similarity < candidate))
                    .label("newly_rejected"),
                    # Rejected before, accepted now.
                    func.count()
                    .filter(and_(rows.c.decision == "rejected", rows.c.similarity >= candidate))
                    .label("newly_accepted"),
                ).select_from(rows)
            )
        ).one()

        result.comparable = int(totals.comparable or 0)
        result.original_verified = int(totals.verified or 0)
        result.original_rejected = int(totals.rejected or 0)
        result.simulated_verified = int(totals.sim_verified or 0)
        result.simulated_rejected = result.comparable - result.simulated_verified
        result.newly_rejected = int(totals.newly_rejected or 0)
        result.newly_accepted = int(totals.newly_accepted or 0)

        result.examples = await self._examples(since, candidate)
        result.histogram = await self._histogram(since)
        return result

    async def _examples(self, since: datetime, candidate: Decimal) -> list[Flip]:
        """The sessions that would flip, newest first.

        Ordered by how *marginal* they are — the rows closest to the candidate
        threshold are the ones a human should look at, because they are where the
        decision was nearly a coin toss either way.
        """
        flipped = self._scope(since).where(
            (
                (VerificationSession.decision == "verified")
                & (VerificationSession.similarity < candidate)
            )
            | (
                (VerificationSession.decision == "rejected")
                & (VerificationSession.similarity >= candidate)
            )
        )

        subquery = flipped.subquery()
        rows = (
            await self.session.execute(
                select(subquery, Subject.external_id)
                .outerjoin(Subject, subquery.c.subject_id == Subject.id)
                .order_by(func.abs(subquery.c.similarity - candidate))
                .limit(MAX_EXAMPLES)
            )
        ).all()

        examples: list[Flip] = []
        for row in rows:
            similarity = float(row.similarity)
            simulated = "verified" if similarity >= float(candidate) else "rejected"
            examples.append(
                Flip(
                    id=row.id,
                    subject_id=row.subject_id,
                    subject_external_id=row.external_id,
                    similarity=similarity,
                    original_decision=row.decision,
                    simulated_decision=simulated,
                    confidence=row.confidence,
                    created_at=row.created_at,
                )
            )
        return examples

    async def _histogram(self, since: datetime, buckets: int = 20) -> list[dict[str, float]]:
        """Similarity distribution across the window.

        Drawn behind the threshold marker so a customer can see whether they are
        about to move it through a dense part of their traffic or an empty one.
        That difference is the whole decision, and a bare number cannot show it.
        """
        width = 1.0 / buckets
        subquery = self._scope(since).subquery()

        # `floor(similarity / width)` rather than Postgres' `width_bucket`, so the
        # same query runs on SQLite in the test suite.
        rows = (
            await self.session.execute(
                select(
                    func.floor(subquery.c.similarity / width).label("bucket"),
                    # `total`, not `count`: a SQLAlchemy Row inherits tuple's
                    # `.count` *method*, so `row.count` would return a bound
                    # method rather than the column and fail at runtime.
                    func.count().label("total"),
                )
                .group_by("bucket")
                .order_by("bucket")
            )
        ).all()

        counts = {int(row.bucket): int(row.total) for row in rows}
        return [
            {
                "from": round(index * width, 3),
                "to": round((index + 1) * width, 3),
                "count": counts.get(index, 0),
            }
            for index in range(buckets)
        ]
