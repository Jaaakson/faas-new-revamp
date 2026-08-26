"""Demo tenant seed.

Realistic seed data is not cosmetic. Charts, empty states, and pagination cannot
be evaluated against three hand-typed rows, and a demo to an investor with an
empty dashboard is a demo of nothing (docs/06-database.md §7).

The generated data is deliberately *imperfect*: a weekday/weekend rhythm, a
night-shift dip in success rate, and a two-day anomaly window. Uniformly random
data produces flat charts that look synthetic and teach nobody how to read the
dashboard.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Role as RoleEnum
from app.core.security import hash_password
from app.modules.analytics.service import AnalyticsService
from app.modules.biometrics.engine.fake import FakeFaceEngine, synthetic_image
from app.modules.biometrics.models import (
    AuditAction,
    AuditLog,
    EnrollmentAttempt,
    FaceProfile,
    FaceTemplate,
    Subject,
    UsageDaily,
    VerificationSession,
)
from app.modules.identity.models import Membership, Organization, OrgSettings, User
from app.modules.identity.seed import get_system_role

logger = structlog.get_logger(__name__)

# Printed by `app.cli seed` and documented in the README. Not a secret —
# the demo tenant exists to be signed into.
DEMO_PASSWORD = "Password123!demo"  # noqa: S105
DEMO_ORG_SLUG = "acme-corp"

# A subdomain of example.com, not .test. RFC 2606 reserves both, but
# `email-validator` — which backs Pydantic's EmailStr — rejects the special-use
# TLDs (.test, .invalid, .localhost) outright, so seeded accounts using them
# could be created but never logged into. example.com validates like any real
# domain while remaining incapable of delivering mail to a real person.
DEMO_DOMAIN = "acme.example.com"

DEMO_USERS = [
    (f"owner@{DEMO_DOMAIN}", "Rani Wulandari", RoleEnum.OWNER),
    (f"admin@{DEMO_DOMAIN}", "Adit Pratama", RoleEnum.ADMIN),
    (f"dev@{DEMO_DOMAIN}", "Bagas Nugroho", RoleEnum.DEVELOPER),
    (f"compliance@{DEMO_DOMAIN}", "Sari Handayani", RoleEnum.VIEWER),
]

FIRST_NAMES = [
    "Rani",
    "Adit",
    "Bagas",
    "Sari",
    "Dewi",
    "Eko",
    "Fitri",
    "Gilang",
    "Hana",
    "Indra",
    "Joko",
    "Kirana",
    "Lestari",
    "Mira",
    "Nadia",
    "Oka",
    "Putri",
    "Rizky",
    "Siti",
    "Taufik",
    "Umar",
    "Vina",
    "Wahyu",
    "Yuni",
    "Zaki",
]
LAST_NAMES = [
    "Wulandari",
    "Pratama",
    "Nugroho",
    "Handayani",
    "Santoso",
    "Kusuma",
    "Halim",
    "Setiawan",
    "Maulana",
    "Permata",
]

# Weighted so the shape resembles real traffic: most inconclusive results are
# capture problems, and genuine rejections are comparatively rare.
FAILURE_WEIGHTS = [
    ("low_quality", 42),
    ("no_face_detected", 26),
    ("below_threshold", 18),
    ("multiple_faces", 8),
    ("subject_not_enrolled", 4),
    ("liveness_failed", 2),
]


async def seed_demo(session: AsyncSession, *, reset: bool = False) -> dict[str, int]:
    """Create or refresh the demo tenant. Idempotent."""
    rng = random.Random(20260731)  # noqa: S311 - deterministic demo data, not crypto

    organization = await session.scalar(
        select(Organization).where(Organization.slug == DEMO_ORG_SLUG)
    )

    if organization and reset:
        await _clear_generated_data(session, organization.id)
    elif organization:
        logger.info("demo_seed_skipped", reason="already exists", org=organization.id)
        return {"skipped": 1}

    if organization is None:
        organization = Organization(
            name="Acme Corp",
            slug=DEMO_ORG_SLUG,
            plan="growth",
            billing_email=f"billing@{DEMO_DOMAIN}",
        )
        session.add(organization)
        await session.flush()
        session.add(
            OrgSettings(
                organization_id=organization.id,
                match_threshold=Decimal("0.380"),
                threshold_preset="balanced",
                log_retention_days=90,
            )
        )

    users = await _seed_users(session, organization.id)
    subjects = await _seed_subjects(session, organization.id, rng)
    sessions = await _seed_verifications(session, organization.id, subjects, rng)
    await _seed_audit(session, organization.id, users, rng)

    await session.commit()

    # Analytics reads rollups, never raw sessions — so the seed must produce
    # them or every chart renders empty against a full table.
    days = await AnalyticsService(session).rebuild_rollups(organization.id, days=90)

    logger.info(
        "demo_seed_complete",
        organization_id=organization.id,
        users=len(users),
        subjects=len(subjects),
        verifications=sessions,
        rollup_days=days,
    )
    return {
        "users": len(users),
        "subjects": len(subjects),
        "verifications": sessions,
        "rollup_days": days,
    }


async def _clear_generated_data(session: AsyncSession, organization_id: str) -> None:
    # Order matters. `enrollment_attempts.subject_id` is ON DELETE SET NULL, so
    # deleting subjects first would orphan the attempts rather than remove
    # them, and a re-seed would accumulate history from every previous run.
    # Templates and profiles do cascade, but are listed explicitly so this
    # reads as the full inventory of what a reset destroys.
    for model in (
        VerificationSession,
        UsageDaily,
        AuditLog,
        EnrollmentAttempt,
        FaceTemplate,
        FaceProfile,
        Subject,
    ):
        await session.execute(delete(model).where(model.organization_id == organization_id))
    await session.commit()


async def _seed_users(session: AsyncSession, organization_id: str) -> list[User]:
    # Hash once and reuse: Argon2 is deliberately slow, and four identical
    # passwords do not need four derivations.
    password_hash = hash_password(DEMO_PASSWORD)
    created: list[User] = []

    for email, full_name, role in DEMO_USERS:
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                password_hash=password_hash,
                full_name=full_name,
                email_verified_at=datetime.now(tz=UTC),
            )
            session.add(user)
            await session.flush()

        membership = await session.scalar(
            select(Membership).where(
                Membership.organization_id == organization_id,
                Membership.user_id == user.id,
            )
        )
        if membership is None:
            role_row = await get_system_role(session, role)
            session.add(
                Membership(
                    organization_id=organization_id,
                    user_id=user.id,
                    role_id=role_row.id,
                    status="active",
                    joined_at=datetime.now(tz=UTC),
                )
            )
        created.append(user)

    await session.flush()
    return created


async def _seed_subjects(
    session: AsyncSession, organization_id: str, rng: random.Random
) -> list[Subject]:
    now = datetime.now(tz=UTC)
    subjects: list[Subject] = []

    for index in range(25):
        enrolled_days_ago = rng.randint(5, 60)
        enrolled_at = now - timedelta(days=enrolled_days_ago)
        # A few subjects stay pending on purpose — every status filter in the
        # console needs at least one row, or the filter looks broken.
        status = "enrolled" if index < 22 else "pending"

        subject = Subject(
            organization_id=organization_id,
            external_id=f"user_{84000 + index * 7}",
            display_name=f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
            status=status,
            subject_metadata={
                "tier": rng.choice(["standard", "premium", "enterprise"]),
                "branch": rng.choice(["jkt-01", "bdg-02", "sby-03"]),
            },
            consent_reference=f"consent_{enrolled_at.date().isoformat()}_{index}",
            consent_at=enrolled_at,
            enrolled_at=enrolled_at if status == "enrolled" else None,
        )
        session.add(subject)
        subjects.append(subject)

    await session.flush()
    await _seed_face_profiles(session, organization_id, subjects, rng)
    return subjects


async def _seed_face_profiles(
    session: AsyncSession,
    organization_id: str,
    subjects: list[Subject],
    rng: random.Random,
) -> None:
    """Give every enrolled subject a real profile and templates.

    Before Phase 5 the seed set `status = 'enrolled'` with nothing behind it,
    which left the subject detail page contradicting itself: an "enrolled" badge
    above "no active face profile". A demo that disagrees with itself is worse
    than one with less data in it.

    Embeddings come from `FakeFaceEngine`, so they are deterministic, correctly
    L2-normalised, and mutually distinct — a duplicate search over seeded data
    returns nothing, which is the truthful answer for 22 different people.
    """
    engine = FakeFaceEngine()

    for index, subject in enumerate(subjects):
        if subject.status != "enrolled" or subject.enrolled_at is None:
            continue

        template_count = rng.randint(2, 3)
        frames = [
            np.frombuffer(synthetic_image(1000 + index, quality=0.9), dtype=np.uint8).copy()
            for _ in range(template_count)
        ]
        # Perturb past the header so each capture of one person differs slightly,
        # exactly as three real frames would.
        for position, frame in enumerate(frames):
            frame[-4:] = np.frombuffer((position + 1).to_bytes(4, "little"), dtype=np.uint8)

        model = engine.model
        profile = FaceProfile(
            organization_id=organization_id,
            subject_id=subject.id,
            status="active",
            version=1,
            model_name=model.name,
            model_version=model.version,
            embedding_dim=model.embedding_dim,
            template_count=template_count,
            avg_quality_score=Decimal("0.940"),
            created_at=subject.enrolled_at,
            updated_at=subject.enrolled_at,
        )
        session.add(profile)
        await session.flush()

        for frame in frames:
            face = engine.detect(frame)[0]
            session.add(
                FaceTemplate(
                    organization_id=organization_id,
                    face_profile_id=profile.id,
                    embedding=engine.embed(frame, face),
                    quality_score=Decimal(str(round(rng.uniform(0.86, 0.97), 3))),
                    sharpness=Decimal("0.900"),
                    brightness=Decimal("0.500"),
                    pose_yaw=Decimal("0.00"),
                    pose_pitch=Decimal("0.00"),
                    pose_roll=Decimal("0.00"),
                    bbox=face.bbox.as_dict(),
                    created_at=subject.enrolled_at,
                    updated_at=subject.enrolled_at,
                )
            )

        session.add(
            EnrollmentAttempt(
                organization_id=organization_id,
                subject_id=subject.id,
                face_profile_id=profile.id,
                status="succeeded",
                image_count=template_count,
                accepted_count=template_count,
                quality_report={"images": []},
                source="console",
                latency_ms=rng.randint(380, 900),
                created_at=subject.enrolled_at,
                updated_at=subject.enrolled_at,
            )
        )

    await session.flush()


async def _seed_verifications(
    session: AsyncSession,
    organization_id: str,
    subjects: list[Subject],
    rng: random.Random,
) -> int:
    now = datetime.now(tz=UTC)
    enrolled = [s for s in subjects if s.status == "enrolled"]
    total = 0
    counts: dict[str, int] = {}
    last_seen: dict[str, datetime] = {}

    planned: list[tuple[datetime, Subject, float]] = []

    for days_ago in range(30, -1, -1):
        day = now - timedelta(days=days_ago)
        # Weekends are quieter. A flat volume line reads as fake immediately.
        weekend = day.weekday() >= 5
        base = rng.randint(18, 30) if weekend else rng.randint(38, 62)

        # A deliberate two-day incident, so the dashboard has something worth
        # investigating and the failure-reason chart is not uniform.
        anomaly = days_ago in {11, 12}
        if anomaly:
            base = int(base * 1.4)

        for _ in range(base):
            hour = _sample_hour(rng)
            created_at = day.replace(
                hour=hour,
                minute=rng.randint(0, 59),
                second=rng.randint(0, 59),
                microsecond=0,
            )
            if created_at > now:
                continue

            night = hour < 6 or hour >= 22
            # Night shifts fail more — lighting, not fraud. This is the insight
            # the hour-of-day heatmap is meant to surface.
            success_chance = 0.82 if night else 0.975
            if anomaly:
                success_chance -= 0.22

            planned.append((created_at, rng.choice(enrolled), success_chance))

    # Insert in chronological order so ULIDs increase with created_at.
    #
    # In production that invariant holds for free — rows are written as events
    # happen — and cursor pagination depends on it, ordering by the primary key
    # to get newest-first. Backdated seed rows inserted in generation order
    # break it, which makes "Recent verifications" list out of sequence and
    # would look like a pagination bug rather than a seeding one.
    planned.sort(key=lambda item: item[0])

    for created_at, subject, success_chance in planned:
        session.add(_make_session(organization_id, subject, created_at, success_chance, rng))
        counts[subject.id] = counts.get(subject.id, 0) + 1
        last_seen[subject.id] = max(last_seen.get(subject.id, created_at), created_at)
        total += 1

    for subject in enrolled:
        subject.verification_count = counts.get(subject.id, 0)
        subject.last_verified_at = last_seen.get(subject.id)

    await session.flush()
    return total


def _sample_hour(rng: random.Random) -> int:
    """Business-hours-weighted hour of day."""
    weights = [2, 1, 1, 1, 2, 4, 8, 14, 22, 30, 34, 32, 28, 30, 33, 31, 26, 20, 14, 10, 7, 5, 4, 3]
    return rng.choices(range(24), weights=weights, k=1)[0]


def _make_session(
    organization_id: str,
    subject: Subject,
    created_at: datetime,
    success_chance: float,
    rng: random.Random,
) -> VerificationSession:
    threshold = Decimal("0.380")
    roll = rng.random()

    if roll < success_chance:
        # Genuine matches cluster well above the threshold; a realistic spread
        # includes a few marginal passes, which is what the confidence band and
        # the threshold tick on the score bar exist to communicate.
        similarity = Decimal(str(round(rng.uniform(0.42, 0.93), 5)))
        margin = float(similarity) - float(threshold)
        confidence = "high" if margin >= 0.15 else "medium" if margin >= 0.05 else "low"
        decision, reason = "verified", None
    else:
        reason = rng.choices(
            [name for name, _ in FAILURE_WEIGHTS],
            weights=[weight for _, weight in FAILURE_WEIGHTS],
            k=1,
        )[0]
        confidence = None
        if reason == "below_threshold":
            decision = "rejected"
            similarity = Decimal(str(round(rng.uniform(0.05, 0.37), 5)))
        else:
            decision = "inconclusive"
            similarity = None

    detect = rng.randint(48, 96)
    embed = rng.randint(110, 190)
    match = rng.randint(18, 44)
    overhead = rng.randint(20, 55)

    # A long tail, because real systems have one: cold caches, GC pauses,
    # contention. Without it p99 collapses onto p95, the latency histogram fills
    # two buckets, and the chart teaches the reader nothing about what a
    # latency distribution actually looks like.
    tail = rng.random()
    if tail > 0.985:
        overhead += rng.randint(700, 2400)  # rare, genuinely slow
    elif tail > 0.94:
        overhead += rng.randint(120, 450)  # occasional
    elif tail < 0.06:
        overhead -= rng.randint(10, 18)  # a fast path, warm and small

    return VerificationSession(
        organization_id=organization_id,
        subject_id=subject.id,
        decision=decision,
        similarity=similarity,
        threshold_applied=threshold,
        confidence=confidence,
        failure_reason=reason,
        templates_compared=3 if decision in {"verified", "rejected"} else 0,
        quality_report={
            "sharpness": round(rng.uniform(0.35, 0.95), 3),
            "brightness": round(rng.uniform(0.25, 0.85), 3),
        },
        latency_ms=detect + embed + match + overhead,
        detect_ms=detect,
        embed_ms=embed,
        match_ms=match,
        source=rng.choices(["api", "console", "playground"], weights=[88, 8, 4], k=1)[0],
        ip_address=f"103.{rng.randint(1, 254)}.{rng.randint(1, 254)}.{rng.randint(1, 254)}",
        created_at=created_at,
    )


async def _seed_audit(
    session: AsyncSession,
    organization_id: str,
    users: list[User],
    rng: random.Random,
) -> None:
    now = datetime.now(tz=UTC)
    owner = users[0]
    admin = users[1] if len(users) > 1 else owner

    entries = [
        (
            AuditAction.SETTINGS_UPDATED,
            "org_settings",
            {"threshold_preset": ["custom", "balanced"]},
            owner,
            26,
        ),
        (
            AuditAction.MEMBER_INVITED,
            "invitation",
            {"email": f"dev@{DEMO_DOMAIN}", "role": "developer"},
            owner,
            24,
        ),
        (
            AuditAction.MEMBER_ROLE_CHANGED,
            "membership",
            {"role": ["developer", "admin"]},
            owner,
            19,
        ),
        (
            AuditAction.THRESHOLD_UPDATED,
            "org_settings",
            {"match_threshold": ["0.320", "0.380"]},
            owner,
            14,
        ),
        (AuditAction.SUBJECT_DELETED, "subject", {"reason": "data subject request"}, admin, 9),
        (
            AuditAction.ORGANIZATION_UPDATED,
            "organization",
            {"name": ["Acme", "Acme Corp"]},
            owner,
            5,
        ),
        (
            AuditAction.MEMBER_INVITED,
            "invitation",
            {"email": f"compliance@{DEMO_DOMAIN}", "role": "viewer"},
            admin,
            3,
        ),
    ]

    for action, resource_type, changes, actor, days_ago in entries:
        session.add(
            AuditLog(
                organization_id=organization_id,
                actor_type="user",
                actor_id=actor.id,
                actor_email=actor.email,
                action=action,
                resource_type=resource_type,
                resource_id=None,
                changes=changes,
                ip_address=f"103.{rng.randint(1, 254)}.{rng.randint(1, 254)}.12",
                created_at=now - timedelta(days=days_ago, hours=rng.randint(0, 23)),
            )
        )

    await session.flush()
