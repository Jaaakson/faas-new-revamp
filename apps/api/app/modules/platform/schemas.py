"""Platform schemas — health, readiness, service metadata."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Liveness. Answers "is this process running", nothing more."""

    status: Literal["ok"] = "ok"
    service: str = Field(examples=["Fvas"])
    version: str = Field(examples=["0.1.0"])
    environment: str = Field(examples=["development"])
    # Which face engine this process loaded. Operationally load-bearing: a
    # deploy that silently came up on the fake engine would accept every face,
    # and this is the cheapest way to notice. Also what the load-test script
    # reads to label its own results honestly.
    face_engine: str = Field(examples=["insightface"])

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "ok",
                "service": "Fvas",
                "version": "0.1.0",
                "environment": "development",
            }
        }
    }


class DependencyStatus(BaseModel):
    name: str
    healthy: bool


class ReadinessResponse(BaseModel):
    """Readiness. Answers "can this process serve traffic".

    Returns 503 when a hard dependency is down, so an orchestrator stops
    routing to it instead of serving errors to users.
    """

    status: Literal["ready", "degraded"]
    dependencies: list[DependencyStatus]

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "ready",
                "dependencies": [
                    {"name": "database", "healthy": True},
                    {"name": "redis", "healthy": True},
                ],
            }
        }
    }
