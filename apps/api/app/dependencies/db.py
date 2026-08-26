"""Database session dependency."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped session.

    The transaction boundary is the service method, not this dependency: the
    session is handed over open and the service commits. This only guarantees
    rollback and close however the request ends.
    """
    async for session in get_session():
        yield session
