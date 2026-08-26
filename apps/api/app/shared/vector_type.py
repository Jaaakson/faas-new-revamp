"""Portable embedding column.

`vector(512)` on PostgreSQL, raw float32 bytes on SQLite.

The alternative — making the biometrics tables Postgres-only — would push every
enrollment test onto a service container and slow the suite from seconds to
minutes. Instead the *storage* is portable and only the parts that genuinely
need pgvector (the HNSW index and the `<=>` operator used for duplicate search)
are Postgres-only, with a brute-force fallback documented at the call site.

Values are always L2-normalised float32 by the time they arrive here, so cosine
similarity is a dot product on either backend.
"""

from __future__ import annotations

from typing import Any, cast

import numpy as np
from numpy.typing import NDArray
from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, LargeBinary, literal
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.operators import ColumnOperators
from sqlalchemy.types import TypeDecorator

EMBEDDING_DIM = 512


class _SqliteVector(TypeDecorator[Any]):
    """float32 little-endian bytes. 512 dims = 2048 bytes per template."""

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> bytes | None:
        if value is None:
            return None
        array = np.asarray(value, dtype=np.float32).ravel()
        if array.size != EMBEDDING_DIM:
            raise ValueError(f"embedding must have {EMBEDDING_DIM} dimensions, got {array.size}")
        return array.tobytes()

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        return np.frombuffer(value, dtype=np.float32)


# Postgres gets the real thing; everything else gets bytes.
Embedding = _SqliteVector().with_variant(Vector(EMBEDDING_DIM), "postgresql")


def is_pgvector_dialect(session: AsyncSession) -> bool:
    """Whether this session can run vector operators.

    The caller uses this to choose between an indexed `<=>` search and a
    brute-force scan in Python. Read from the bound engine rather than from
    settings, so a test that points at PostgreSQL exercises the real path
    without any configuration.
    """
    return bool(session.bind and session.bind.dialect.name == "postgresql")


def cosine_distance(
    column: ColumnOperators, embedding: NDArray[np.float32]
) -> ColumnElement[float]:
    """`embedding <=> $1::vector` — cosine distance, which is `1 - similarity`.

    Built as an explicit operator rather than through pgvector's comparator, for
    two independent reasons:

    * `with_variant` keeps the *base* type's comparator, so `.cosine_distance()`
      is genuinely not reachable on this column — the SQLite variant is the base
      and it has no vector methods. Verified, not assumed.
    * PostgreSQL matches indexes on operator identity. `cosine_distance(a, b)`
      is a plain function call and plans as a sort; `a <=> b` is what the HNSW
      index is built for. The two forms compute the same number.

    Necessary but *not* sufficient. The index only helps when the `ORDER BY`
    applies to a scan of `face_templates` alone — join first and the ordering
    lands on the join's output, the planner must sort, and it falls back to a
    sequential scan even with this operator. See `_search_pgvector`, which
    nests the search in a subquery for exactly that reason. Both facts were
    established with `EXPLAIN` on 5,000 rows, not assumed.
    """
    vector = np.asarray(embedding, dtype=np.float32).ravel()
    if vector.size != EMBEDDING_DIM:
        raise ValueError(f"embedding must have {EMBEDDING_DIM} dimensions, got {vector.size}")
    bound = literal(vector.tolist(), type_=Vector(EMBEDDING_DIM))
    # `op()` is declared on Operators and returns Operators; the concrete
    # result for a column expression is always a BinaryExpression.
    return cast("ColumnElement[float]", column.op("<=>", return_type=Float)(bound))
