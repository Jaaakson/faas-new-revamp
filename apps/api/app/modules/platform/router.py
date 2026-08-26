"""Platform endpoints: liveness and readiness.

Kept off the versioned prefix on purpose — these are operational probes, not
part of the public API contract, and an orchestrator should not have to know
about API versioning to check whether a container is alive.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Response, status

from app.core.config import settings
from app.core.database import check_database
from app.core.redis import check_redis
from app.modules.platform.schemas import (
    DependencyStatus,
    HealthResponse,
    ReadinessResponse,
)

router = APIRouter(tags=["Platform"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
    description=(
        "Returns 200 whenever the process is running. Deliberately checks no "
        "dependencies: a database outage should not cause the orchestrator to "
        "restart healthy containers in a loop."
    ),
)
async def health() -> HealthResponse:
    return HealthResponse(
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        face_engine=settings.FACE_ENGINE,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description=(
        "Reports connectivity to every hard dependency. Returns 503 when any "
        "is unreachable so the load balancer stops routing traffic here."
    ),
    responses={503: {"model": ReadinessResponse, "description": "A dependency is down"}},
)
async def ready(response: Response) -> ReadinessResponse:
    # Probe concurrently: two sequential 2s timeouts would make a readiness
    # check slower than the orchestrator's own probe timeout.
    database_ok, redis_ok = await asyncio.gather(check_database(), check_redis())

    dependencies = [
        DependencyStatus(name="database", healthy=database_ok),
        DependencyStatus(name="redis", healthy=redis_ok),
    ]
    healthy = all(dependency.healthy for dependency in dependencies)

    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ready" if healthy else "degraded",
        dependencies=dependencies,
    )
