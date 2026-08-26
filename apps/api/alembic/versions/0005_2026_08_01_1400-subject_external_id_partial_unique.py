"""make the subject external_id uniqueness partial on deleted_at

Revision ID: 0005
Revises: 0004
Created: 2026-08-01

Deleting a subject soft-deletes the row while physically destroying its
templates (docs/09-security.md §5). Under a plain unique index that would
permanently poison the customer's `external_id`: re-onboarding the same person
would collide with the tombstone of their deleted record, and the customer's own
identifier is not something they can change.

Making the index partial on `deleted_at IS NULL` scopes uniqueness to live rows,
which is what the constraint was always meant to say.

Expand-then-contract is unnecessary here — this is a single index swap on a table
that is empty in every environment that has run 0003, and both statements are in
one transaction.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "uq_subjects_org_external"


def upgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="subjects")
    op.create_index(
        INDEX_NAME,
        "subjects",
        ["organization_id", "external_id"],
        unique=True,
        postgresql_where="deleted_at IS NULL",
        sqlite_where="deleted_at IS NULL",
    )


def downgrade() -> None:
    # Only reversible while no two rows share (organization_id, external_id) —
    # which is exactly what the partial index permitted. A downgrade on data
    # that used the new freedom will fail here rather than silently drop rows,
    # and failing is the correct outcome.
    op.drop_index(INDEX_NAME, table_name="subjects")
    op.create_index(
        INDEX_NAME,
        "subjects",
        ["organization_id", "external_id"],
        unique=True,
    )
