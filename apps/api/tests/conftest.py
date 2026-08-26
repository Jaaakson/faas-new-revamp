"""Shared test fixtures.

The suite runs on either engine, selected by `TEST_DATABASE_URL`:

* **SQLite in-memory (default)** — no services to start, the whole run finishes
  in seconds, and it covers every push.
* **PostgreSQL** — the same tests against the real engine, catching what SQLite
  cannot model: JSONB, `citext`, native partial indexes, and server-side default
  behaviour.

      TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:15432/fvas_test

CI runs both. Keeping one suite rather than a separate "integration" set means
no test is accidentally exempt from the fidelity run.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

# Set before any app import so Settings picks it up.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LOG_FORMAT", "console")
os.environ.setdefault("LOG_LEVEL", "WARNING")
# Argon2 at production cost would add ~100 ms per hashed password; the suite
# hashes dozens. Parameters are still exercised — only the cost is lowered.
os.environ.setdefault("ARGON2_TIME_COST", "1")
os.environ.setdefault("ARGON2_MEMORY_COST", "8192")
os.environ.setdefault("ARGON2_PARALLELISM", "1")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.redis import check_redis, close_redis
from app.dependencies.db import get_db
from app.main import create_app
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.biometrics import models as biometrics_models  # noqa: F401
from app.modules.biometrics.engine.registry import load_engine, reset_engine
from app.modules.identity import models as identity_models  # noqa: F401
from app.modules.identity.seed import seed_roles_and_permissions
from app.shared.base_model import Base

# Point the suite at a real PostgreSQL to catch behaviour SQLite cannot model:
#
#   TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:15432/fvas_test
#
# Defaults to in-memory SQLite so `pytest` stays fast and needs no services.
# CI runs both — SQLite for speed on every push, Postgres for fidelity.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
IS_POSTGRES = TEST_DATABASE_URL.startswith("postgresql")


@pytest.fixture
async def engine():  # type: ignore[no-untyped-def]
    """A fresh database per test.

    On SQLite, StaticPool keeps every connection pointed at the same in-memory
    database — without it each connection would get its own empty one. On
    PostgreSQL the schema is dropped and recreated per test instead, which is
    slower but gives each test the same clean slate.
    """
    from sqlalchemy.pool import NullPool, StaticPool

    if IS_POSTGRES:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    else:
        engine = create_async_engine(
            TEST_DATABASE_URL,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )

        # SQLite ignores foreign keys unless asked. Leaving them off would let
        # the suite pass while production rejects the same write.
        @event.listens_for(engine.sync_engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    async with engine.begin() as connection:
        if IS_POSTGRES:
            # pgvector is required from Phase 5; creating it here keeps the test
            # schema identical to what the migrations produce.
            await connection.execute(text('CREATE EXTENSION IF NOT EXISTS "vector"'))
            await connection.execute(text('CREATE EXTENSION IF NOT EXISTS "citext"'))
            await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    yield engine

    if IS_POSTGRES:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def session_factory(engine):  # type: ignore[no-untyped-def]
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def session(session_factory) -> AsyncIterator[AsyncSession]:  # type: ignore[no-untyped-def]
    """A seeded session. Roles and permissions exist, as in a migrated database."""
    async with session_factory() as db_session:
        await seed_roles_and_permissions(db_session)
        await db_session.commit()
        yield db_session


@pytest.fixture(autouse=True)
async def redis_client():  # type: ignore[no-untyped-def]
    """Drop the Redis connection between tests.

    The client is a process-wide singleton bound to whatever event loop created
    it, and pytest-asyncio gives each test a fresh loop. Without this, the
    second test to touch Redis reuses a connection whose loop is closed and
    fails with `RuntimeError: Event loop is closed` — which looks like a Redis
    problem and is not.
    """
    yield
    await close_redis()


@pytest.fixture
async def requires_redis():  # type: ignore[no-untyped-def]
    """Skip when Redis is not running.

    Rate limiting and idempotency both degrade gracefully without it, so most of
    the suite passes regardless. The tests that assert the *undegraded*
    behaviour cannot, and skipping is more honest than a green run that proved
    nothing.
    """
    if not await check_redis():
        pytest.skip("Redis is not available")


@pytest.fixture(autouse=True)
def face_engine():  # type: ignore[no-untyped-def]
    """Install the fake engine for every test.

    Autouse because `ASGITransport` does not run the lifespan, which is where
    the real app loads the engine. Without this, any test touching an enrollment
    endpoint would fail on "Face engine not loaded" — an artefact of the
    transport, not a defect worth reproducing in every test.

    Reset on both sides so a test that installs its own engine cannot leak it
    into the next one.
    """
    reset_engine()
    engine = load_engine()
    yield engine
    reset_engine()


@pytest.fixture
async def app(session_factory):  # type: ignore[no-untyped-def]
    """The real app, with the database dependency pointed at the test engine."""
    application = create_app()

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as db_session:
            yield db_session

    application.dependency_overrides[get_db] = _override_get_db
    return application


@pytest.fixture
async def client(app, session) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    """HTTP client driving the ASGI app in-process — no network, no server.

    Depends on `session` so the RBAC seed has run before any request.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as http_client:
        yield http_client
