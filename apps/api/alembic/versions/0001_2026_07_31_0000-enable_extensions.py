"""enable required postgres extensions

Revision ID: 0001
Revises:
Created: 2026-07-31

Phase 1 defines no tables. It establishes the extensions every later phase
depends on, so a fresh database is correct before the first model lands:

  - vector  : 512-d ArcFace embeddings and the HNSW index used for duplicate
              detection at enrollment (docs/06-database.md §4.3)
  - citext  : case-insensitive email columns, so Rani@acme.io and rani@acme.io
              cannot both register
  - pgcrypto: gen_random_bytes for token generation inside the database

Extensions are created idempotently. Downgrade drops them, which is safe only
because nothing depends on them at this revision — later revisions must never
drop these.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EXTENSIONS = ("vector", "citext", "pgcrypto")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for extension in EXTENSIONS:
        op.execute(f'CREATE EXTENSION IF NOT EXISTS "{extension}"')


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for extension in reversed(EXTENSIONS):
        op.execute(f'DROP EXTENSION IF EXISTS "{extension}"')
