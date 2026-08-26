"""Data access for subjects, profiles and templates.

Private to this module — other modules call `SubjectService` or
`EnrollmentService`, never these classes (docs/05-architecture.md §2).

Every read starts from `_scoped()`, so the tenant filter is structural rather
than remembered. The one query that cannot use it — the duplicate search, which
joins templates to profiles — carries its `organization_id` predicate explicitly
and is covered by a cross-tenant test for exactly that reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import CursorResult, delete, func, select

from app.modules.biometrics.models import (
    EnrollmentAttempt,
    FaceProfile,
    FaceTemplate,
    Subject,
)
from app.shared.base_repository import TenantScopedRepository
from app.shared.vector_type import cosine_distance, is_pgvector_dialect


@dataclass(frozen=True, slots=True)
class DuplicateHit:
    subject_id: str
    face_profile_id: str
    similarity: float


class SubjectRepository(TenantScopedRepository[Subject]):
    model = Subject

    async def get_by_external_id(self, external_id: str) -> Subject | None:
        result = await self.session.execute(
            self._scoped().where(Subject.external_id == external_id)
        )
        return result.scalar_one_or_none()

    async def external_id_exists(self, external_id: str) -> bool:
        result = await self.session.execute(
            select(func.count())
            .select_from(Subject)
            .where(
                Subject.organization_id == self.organization_id,
                Subject.external_id == external_id,
                Subject.deleted_at.is_(None),
            )
        )
        return (result.scalar_one() or 0) > 0


class FaceProfileRepository(TenantScopedRepository[FaceProfile]):
    model = FaceProfile

    async def get_active(self, subject_id: str) -> FaceProfile | None:
        result = await self.session.execute(
            self._scoped().where(
                FaceProfile.subject_id == subject_id,
                FaceProfile.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def list_for_subject(self, subject_id: str) -> list[FaceProfile]:
        result = await self.session.execute(
            self._scoped()
            .where(FaceProfile.subject_id == subject_id)
            .order_by(FaceProfile.version.desc())
        )
        return list(result.scalars())

    async def highest_version(self, subject_id: str) -> int:
        """Including superseded and revoked profiles.

        Versions must never be reused: an audit trail that has two different
        "version 2" profiles for one subject cannot explain a past decision.
        """
        result = await self.session.execute(
            select(func.max(FaceProfile.version)).where(
                FaceProfile.organization_id == self.organization_id,
                FaceProfile.subject_id == subject_id,
            )
        )
        return int(result.scalar_one() or 0)


class FaceTemplateRepository(TenantScopedRepository[FaceTemplate]):
    model = FaceTemplate

    async def list_for_profile(self, face_profile_id: str) -> list[FaceTemplate]:
        result = await self.session.execute(
            self._scoped()
            .where(FaceTemplate.face_profile_id == face_profile_id)
            .order_by(FaceTemplate.quality_score.desc())
        )
        return list(result.scalars())

    async def delete_for_subject(self, subject_id: str) -> int:
        """Physically remove every template belonging to a subject.

        A `DELETE`, not a flag. `face_templates` has no `deleted_at` by design
        (docs/06-database.md §4.3) — a soft-deleted biometric template is still
        retained biometric data.

        Expressed as a set-based statement rather than an ORM cascade so it
        holds even when the profiles were never loaded into the session, and so
        the row count can be asserted in a test.
        """
        profile_ids = select(FaceProfile.id).where(
            FaceProfile.organization_id == self.organization_id,
            FaceProfile.subject_id == subject_id,
        )
        # A DML statement always yields a CursorResult; `execute` is typed as
        # returning the broader Result, which has no rowcount.
        result: CursorResult[Any] = await self.session.execute(  # type: ignore[assignment]
            delete(FaceTemplate).where(
                FaceTemplate.organization_id == self.organization_id,
                FaceTemplate.face_profile_id.in_(profile_ids),
            )
        )
        return int(result.rowcount or 0)

    async def search_duplicates(
        self,
        embedding: NDArray[np.float32],
        *,
        exclude_subject_id: str | None,
        threshold: float,
        limit: int = 5,
    ) -> list[DuplicateHit]:
        """Find already-enrolled faces close to this one.

        The one genuine 1:N search in the product, and the only reason the HNSW
        index exists. Verification never comes here — it loads at most five
        templates by profile id and compares them exactly, so an authentication
        decision never rides on approximate-nearest-neighbour recall
        (docs/06-database.md §4.3).

        Only `active` profiles participate. A superseded profile represents a
        face the subject has re-enrolled past, and a revoked one represents data
        the customer asked us to stop matching against; treating either as a
        duplicate would block a legitimate re-onboarding.

        That filter is a safety net rather than a load-bearing predicate: the
        service physically deletes templates whenever a profile stops being
        active, so in a consistent database every template already belongs to an
        active profile. `test_no_template_outlives_its_active_profile` holds it.
        """
        if is_pgvector_dialect(self.session):
            return await self._search_pgvector(
                embedding,
                exclude_subject_id=exclude_subject_id,
                threshold=threshold,
                limit=limit,
            )
        return await self._search_in_python(
            embedding,
            exclude_subject_id=exclude_subject_id,
            threshold=threshold,
            limit=limit,
        )

    async def _search_pgvector(
        self,
        embedding: NDArray[np.float32],
        *,
        exclude_subject_id: str | None,
        threshold: float,
        limit: int,
    ) -> list[DuplicateHit]:
        """The ANN search, shaped so the planner can actually use the index.

        The nesting is not stylistic. An HNSW index scan supplies rows in
        distance order, and that order is what satisfies `ORDER BY ... LIMIT`.
        Join first and the ordering is applied to the join's output instead —
        the planner has no choice but a full sort, and it falls back to a
        sequential scan over every template in the database.

        Measured on 5,000 templates, `EXPLAIN` on the joined form:

            Sort -> Hash Join -> Seq Scan on face_templates

        and on this form:

            Nested Loop -> Limit -> Index Scan using ix_face_templates_embedding_hnsw
                                      Order By: (embedding <=> $1)

        Using the `<=>` operator rather than `cosine_distance(a, b)` is
        necessary too — PostgreSQL matches indexes on operator identity, and the
        function form plans as a sort even here — but on its own it is not
        sufficient. Both had to be right.
        """
        # Over-fetch, then collapse: several templates of one person rank
        # together, and the subject being enrolled is filtered out afterwards
        # rather than inside, because a predicate on the joined table would
        # reintroduce exactly the join this shape exists to avoid.
        candidates = max(limit * 10, 50)
        distance = cosine_distance(FaceTemplate.embedding, embedding)

        nearest = (
            select(
                FaceTemplate.face_profile_id.label("face_profile_id"),
                distance.label("distance"),
            )
            .where(FaceTemplate.organization_id == self.organization_id)
            .order_by(distance)
            .limit(candidates)
            .subquery()
        )

        statement = (
            select(FaceProfile.subject_id, FaceProfile.id, nearest.c.distance)
            .select_from(nearest)
            .join(FaceProfile, nearest.c.face_profile_id == FaceProfile.id)
            .where(FaceProfile.status == "active")
            .order_by(nearest.c.distance)
        )
        if exclude_subject_id:
            statement = statement.where(FaceProfile.subject_id != exclude_subject_id)

        rows = (await self.session.execute(statement)).all()
        return _collapse_by_subject(
            ((row[0], row[1], 1.0 - float(row[2])) for row in rows),
            threshold=threshold,
            limit=limit,
        )

    async def _search_in_python(
        self,
        embedding: NDArray[np.float32],
        *,
        exclude_subject_id: str | None,
        threshold: float,
        limit: int,
    ) -> list[DuplicateHit]:
        """SQLite fallback: load and compare in memory.

        Only ever runs in the test suite, where a tenant holds tens of templates.
        It exists so the *behaviour* under test is the real duplicate policy
        rather than a mock, and it would be indefensible at production scale —
        which is why the dialect check above is not a configuration option.
        """
        statement = (
            select(FaceProfile.subject_id, FaceProfile.id, FaceTemplate.embedding)
            .join(FaceProfile, FaceTemplate.face_profile_id == FaceProfile.id)
            .where(
                FaceTemplate.organization_id == self.organization_id,
                FaceProfile.status == "active",
            )
        )
        if exclude_subject_id:
            statement = statement.where(FaceProfile.subject_id != exclude_subject_id)

        probe = embedding.ravel()
        rows = (await self.session.execute(statement)).all()
        scored = (
            (row[0], row[1], float(np.dot(np.asarray(row[2], dtype=np.float32).ravel(), probe)))
            for row in rows
        )
        return _collapse_by_subject(scored, threshold=threshold, limit=limit)


def _collapse_by_subject(
    hits: object,
    *,
    threshold: float,
    limit: int,
) -> list[DuplicateHit]:
    """One row per subject, keeping their best-matching template.

    Five templates of the same person would otherwise fill the whole result and
    hide a second, genuinely different match.
    """
    best: dict[str, DuplicateHit] = {}
    for subject_id, profile_id, similarity in hits:  # type: ignore[attr-defined]
        if similarity < threshold:
            continue
        current = best.get(subject_id)
        if current is None or similarity > current.similarity:
            best[subject_id] = DuplicateHit(
                subject_id=subject_id,
                face_profile_id=profile_id,
                similarity=similarity,
            )

    ranked = sorted(best.values(), key=lambda hit: hit.similarity, reverse=True)
    return ranked[:limit]


class EnrollmentAttemptRepository(TenantScopedRepository[EnrollmentAttempt]):
    model = EnrollmentAttempt

    async def list_for_subject(
        self, subject_id: str, *, limit: int = 20
    ) -> list[EnrollmentAttempt]:
        result = await self.session.execute(
            self._scoped()
            .where(EnrollmentAttempt.subject_id == subject_id)
            .order_by(EnrollmentAttempt.id.desc())
            .limit(limit)
        )
        return list(result.scalars())
