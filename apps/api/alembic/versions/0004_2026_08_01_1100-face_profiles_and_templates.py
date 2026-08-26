"""face profiles, templates and enrollment attempts

Revision ID: 0004
Revises: 0003
Created: 2026-08-01

The biometric tables. Two properties are enforced here rather than in the
service layer, because a bug above them must not be able to violate either:

  * `face_templates` has no `deleted_at` — deletion is physical.
  * A partial unique index allows exactly one active profile per subject.

The HNSW index is PostgreSQL-only. It exists solely for duplicate detection at
enrollment, which is a genuine 1:N search; verification loads at most five
templates by profile id and compares them exactly, so an authentication
decision never depends on approximate-nearest-neighbour recall
(docs/06-database.md §4.3).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from app.shared.vector_type import EMBEDDING_DIM

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_COLUMN = sa.JSON().with_variant(JSONB(), "postgresql")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _embedding_column() -> sa.Column:
    """`vector(512)` on Postgres, float32 bytes elsewhere."""
    if op.get_bind().dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector

        return sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False)
    return sa.Column("embedding", sa.LargeBinary(), nullable=False)


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"

    op.create_table(
        "face_profiles",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(40),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subject_id",
            sa.String(40),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("model_name", sa.String(32), nullable=False),
        sa.Column("model_version", sa.String(32), nullable=False),
        sa.Column("embedding_dim", sa.Integer(), nullable=False, server_default="512"),
        sa.Column("template_count", sa.Integer(), nullable=False),
        sa.Column("avg_quality_score", sa.Numeric(4, 3), nullable=True),
        sa.Column("enrolled_by_user_id", sa.String(40), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'revoked')", name="ck_face_profiles_status"
        ),
    )
    op.create_index(
        "uq_face_profiles_active_subject",
        "face_profiles",
        ["subject_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_face_profiles_org_subject", "face_profiles", ["organization_id", "subject_id"]
    )

    op.create_table(
        "face_templates",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(40),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "face_profile_id",
            sa.String(40),
            sa.ForeignKey("face_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        _embedding_column(),
        sa.Column("quality_score", sa.Numeric(4, 3), nullable=False),
        sa.Column("sharpness", sa.Numeric(4, 3), nullable=True),
        sa.Column("brightness", sa.Numeric(4, 3), nullable=True),
        sa.Column("pose_yaw", sa.Numeric(5, 2), nullable=True),
        sa.Column("pose_pitch", sa.Numeric(5, 2), nullable=True),
        sa.Column("pose_roll", sa.Numeric(5, 2), nullable=True),
        sa.Column("bbox", JSON_COLUMN, nullable=True),
        sa.Column("image_ref", sa.String(255), nullable=True),
        *_timestamps(),
        # Deliberately no deleted_at. See the module docstring.
    )
    op.create_index("ix_face_templates_profile", "face_templates", ["face_profile_id"])
    op.create_index("ix_face_templates_org", "face_templates", ["organization_id"])

    if is_postgres:
        # Duplicate detection only. m/ef_construction are pgvector's documented
        # defaults — tune once real template volume exists, not before.
        op.execute(
            "CREATE INDEX ix_face_templates_embedding_hnsw "
            "ON face_templates USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )

    op.create_table(
        "enrollment_attempts",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(40),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subject_id",
            sa.String(40),
            sa.ForeignKey("subjects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "face_profile_id",
            sa.String(40),
            sa.ForeignKey("face_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("failure_reason", sa.String(32), nullable=True),
        sa.Column("image_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quality_report", JSON_COLUMN, nullable=True),
        sa.Column("duplicate_subject_id", sa.String(40), nullable=True),
        sa.Column("duplicate_similarity", sa.Numeric(6, 5), nullable=True),
        sa.Column("enrolled_by_user_id", sa.String(40), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="api"),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed', 'duplicate_detected')",
            name="ck_enrollment_attempts_status",
        ),
    )
    op.create_index(
        "ix_enrollments_org_created", "enrollment_attempts", ["organization_id", "created_at"]
    )
    op.create_index(
        "ix_enrollments_org_subject",
        "enrollment_attempts",
        ["organization_id", "subject_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("enrollment_attempts")
    op.drop_table("face_templates")
    op.drop_table("face_profiles")
