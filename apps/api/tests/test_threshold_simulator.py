"""Threshold simulation.

The arithmetic here is simple, which is exactly why it needs testing: an
off-by-one on a comparison operator would produce plausible-looking numbers that
are quietly wrong, and a customer would move a security threshold based on them.

Sessions are built with known similarities so every expected count can be
derived by hand rather than by re-running the implementation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.simulator import ThresholdSimulator
from app.modules.biometrics.models import Subject, VerificationSession
from app.modules.identity.models import Organization, OrgSettings
from tests.factories import Account, register

CURRENT = Decimal("0.380")


async def _org(session: AsyncSession, identifier: str = "org_sim") -> str:
    session.add(Organization(id=identifier, name="Sim", slug=identifier))
    await session.flush()
    session.add(OrgSettings(organization_id=identifier, match_threshold=CURRENT))
    session.add(Subject(id=f"sub_{identifier}", organization_id=identifier, external_id="person"))
    await session.commit()
    return identifier


def _session_row(
    organization_id: str,
    *,
    similarity: float | None,
    decision: str,
    age_days: int = 1,
) -> VerificationSession:
    moment = datetime.now(tz=UTC) - timedelta(days=age_days)
    return VerificationSession(
        organization_id=organization_id,
        subject_id=f"sub_{organization_id}",
        decision=decision,
        similarity=Decimal(str(similarity)) if similarity is not None else None,
        threshold_applied=CURRENT,
        created_at=moment,
        updated_at=moment,
    )


async def test_raising_the_threshold_flips_marginal_accepts_to_rejects(
    session: AsyncSession,
) -> None:
    """Three accepts at 0.40, 0.50, 0.90. At 0.45 exactly one should flip."""
    org = await _org(session)
    session.add_all(
        [
            _session_row(org, similarity=0.40, decision="verified"),
            _session_row(org, similarity=0.50, decision="verified"),
            _session_row(org, similarity=0.90, decision="verified"),
        ]
    )
    await session.commit()

    result = await ThresholdSimulator(session, org).run(candidate=Decimal("0.45"), current=CURRENT)

    assert result.comparable == 3
    assert result.newly_rejected == 1
    assert result.newly_accepted == 0
    assert result.simulated_verified == 2
    assert result.unchanged == 2


async def test_lowering_the_threshold_flips_rejects_to_accepts(
    session: AsyncSession,
) -> None:
    org = await _org(session)
    session.add_all(
        [
            _session_row(org, similarity=0.10, decision="rejected"),
            _session_row(org, similarity=0.35, decision="rejected"),
            _session_row(org, similarity=0.37, decision="rejected"),
        ]
    )
    await session.commit()

    result = await ThresholdSimulator(session, org).run(candidate=Decimal("0.30"), current=CURRENT)

    assert result.newly_accepted == 2
    assert result.newly_rejected == 0
    assert result.simulated_verified == 2


async def test_the_boundary_is_inclusive_and_matches_the_live_decision_rule(
    session: AsyncSession,
) -> None:
    """`similarity >= threshold` verifies — the same comparison the service uses.

    If the simulator used `>` while verification uses `>=`, a session sitting
    exactly on the threshold would be reported as flipping when it would not.
    """
    org = await _org(session)
    session.add(_session_row(org, similarity=0.45, decision="verified"))
    await session.commit()

    exact = await ThresholdSimulator(session, org).run(candidate=Decimal("0.45"), current=CURRENT)
    just_above = await ThresholdSimulator(session, org).run(
        candidate=Decimal("0.451"), current=CURRENT
    )

    assert exact.newly_rejected == 0, "a session exactly on the threshold still verifies"
    assert just_above.newly_rejected == 1


async def test_inconclusive_sessions_are_excluded(session: AsyncSession) -> None:
    """They had no similarity — the pipeline stopped before matching.

    Counting them would inflate the denominator and make the simulation look
    more decisive than it is.
    """
    org = await _org(session)
    session.add_all(
        [
            _session_row(org, similarity=0.90, decision="verified"),
            _session_row(org, similarity=None, decision="inconclusive"),
            _session_row(org, similarity=None, decision="error"),
        ]
    )
    await session.commit()

    result = await ThresholdSimulator(session, org).run(candidate=Decimal("0.50"), current=CURRENT)

    assert result.comparable == 1


async def test_an_identical_threshold_changes_nothing(session: AsyncSession) -> None:
    """The control. If this ever reports a flip, the comparison is wrong."""
    org = await _org(session)
    session.add_all(
        [
            _session_row(org, similarity=0.90, decision="verified"),
            _session_row(org, similarity=0.20, decision="rejected"),
            _session_row(org, similarity=0.38, decision="verified"),
        ]
    )
    await session.commit()

    result = await ThresholdSimulator(session, org).run(candidate=CURRENT, current=CURRENT)

    assert result.newly_rejected == 0
    assert result.newly_accepted == 0
    assert result.acceptance_rate_before == result.acceptance_rate_after


async def test_sessions_outside_the_window_are_ignored(session: AsyncSession) -> None:
    org = await _org(session)
    session.add_all(
        [
            _session_row(org, similarity=0.40, decision="verified", age_days=2),
            _session_row(org, similarity=0.40, decision="verified", age_days=400),
        ]
    )
    await session.commit()

    result = await ThresholdSimulator(session, org).run(
        candidate=Decimal("0.50"), current=CURRENT, days=30
    )

    assert result.comparable == 1
    assert result.newly_rejected == 1


async def test_examples_are_ordered_by_how_marginal_they_are(
    session: AsyncSession,
) -> None:
    """The rows nearest the candidate are where the decision was a coin toss,
    and they are what a human should look at first.
    """
    org = await _org(session)
    session.add_all(
        [
            _session_row(org, similarity=0.10, decision="verified"),
            _session_row(org, similarity=0.44, decision="verified"),
            _session_row(org, similarity=0.30, decision="verified"),
        ]
    )
    await session.commit()

    result = await ThresholdSimulator(session, org).run(candidate=Decimal("0.45"), current=CURRENT)

    assert [round(flip.similarity, 2) for flip in result.examples] == [0.44, 0.30, 0.10]
    assert all(f.original_decision == "verified" for f in result.examples)
    assert all(f.simulated_decision == "rejected" for f in result.examples)


async def test_the_histogram_covers_the_whole_range(session: AsyncSession) -> None:
    """Empty buckets are returned too, so the chart has a continuous axis rather
    than gaps where the tenant happens to have no traffic.
    """
    org = await _org(session)
    session.add_all(
        [
            _session_row(org, similarity=0.05, decision="rejected"),
            _session_row(org, similarity=0.92, decision="verified"),
        ]
    )
    await session.commit()

    result = await ThresholdSimulator(session, org).run(candidate=Decimal("0.50"), current=CURRENT)

    assert len(result.histogram) == 20
    assert sum(bucket["count"] for bucket in result.histogram) == 2
    assert result.histogram[0]["from"] == 0.0
    assert result.histogram[-1]["to"] == 1.0


async def test_the_simulation_never_crosses_a_tenant_boundary(
    session: AsyncSession,
) -> None:
    mine = await _org(session, "org_mine")
    theirs = await _org(session, "org_theirs")
    session.add_all(
        [
            _session_row(mine, similarity=0.40, decision="verified"),
            _session_row(theirs, similarity=0.40, decision="verified"),
        ]
    )
    await session.commit()

    result = await ThresholdSimulator(session, mine).run(candidate=Decimal("0.50"), current=CURRENT)

    assert result.comparable == 1


# ── Through the API ───────────────────────────────────────────────────────────


@pytest.fixture
async def owner(client: AsyncClient) -> Account:
    return await register(client, email="owner@acme.example.com", organization_name="Acme")


async def test_the_endpoint_reports_a_simulation(client: AsyncClient, owner: Account) -> None:
    response = await client.get(
        "/v1/console/threshold/simulate?threshold=0.5&days=30", headers=owner.auth
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidate_threshold"] == 0.5
    assert body["current_threshold"] == 0.38
    assert body["window_days"] == 30
    assert len(body["histogram"]) == 20
    assert "from" in body["histogram"][0]


async def test_an_out_of_range_threshold_is_rejected(client: AsyncClient, owner: Account) -> None:
    for value in ("0", "1", "1.5", "-0.2"):
        response = await client.get(
            f"/v1/console/threshold/simulate?threshold={value}", headers=owner.auth
        )
        assert response.status_code == 400, f"threshold={value} was accepted"


async def test_a_viewer_can_simulate_but_not_change_the_threshold(
    client: AsyncClient, owner: Account
) -> None:
    """Simulation is a read. A compliance officer should be able to ask "what
    would this do" without being able to do it.
    """
    from tests.factories import invite_and_join

    viewer = await invite_and_join(
        client, inviter=owner, email="viewer@acme.example.com", role="viewer"
    )

    simulated = await client.get(
        "/v1/console/threshold/simulate?threshold=0.5", headers=viewer.auth
    )
    changed = await client.patch(
        "/v1/console/organizations/current/settings",
        json={"threshold_preset": "strict"},
        headers=viewer.auth,
    )

    assert simulated.status_code == 200
    assert changed.status_code == 403
