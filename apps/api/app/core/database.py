"""Async database engine and session management."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = structlog.get_logger(__name__)


def _engine_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "echo": settings.DATABASE_ECHO,
        # Recycle before typical proxy/idle timeouts so a pooled connection is
        # never handed out already dead.
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }
    # SQLite (used by the test suite) has no server-side pool to size.
    if not settings.DATABASE_URL.startswith("sqlite"):
        kwargs["pool_size"] = settings.DATABASE_POOL_SIZE
        kwargs["max_overflow"] = settings.DATABASE_MAX_OVERFLOW
    return kwargs


engine: AsyncEngine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs())

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # keep attributes readable after commit
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a session bound to the request.

    The transaction boundary is the service method, not this dependency — the
    session is handed over open, and the service commits. This dependency only
    guarantees the session is rolled back and closed no matter how the request
    ends.
    """
    session = SessionFactory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def check_database() -> bool:
    """Readiness probe. Returns False rather than raising."""
    from sqlalchemy import text

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("database_unavailable", error=str(exc))
        return False


async def dispose_engine() -> None:
    """Close the pool on shutdown."""
    await engine.dispose()
