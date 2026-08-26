# syntax=docker/dockerfile:1.7
# ==============================================================================
# Fvas API
#
# Layer order is deliberate: dependencies, then (from Phase 5) model weights,
# then application code. A code change rebuilds only the last layer, leaving the
# expensive layers cached. Reversing this makes every deploy a long download.
# ==============================================================================

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# libgl1 + libglib2.0-0 are OpenCV's runtime dependencies (Phase 5). Installing
# them here rather than later keeps the base layer stable across phases; without
# them, `import cv2` fails at runtime with an error that costs an hour to
# diagnose the first time.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app


# ── Dependencies ──────────────────────────────────────────────────────────────
FROM base AS deps

# The `face` extra (insightface, onnxruntime, opencv) is ~500 MB installed and
# is needed only by FACE_ENGINE=insightface. It is opt-in so the default image
# stays small and the default build stays fast — the whole test suite and the
# entire console flow run against the fake engine without it:
#
#   docker compose build --build-arg INSTALL_FACE_EXTRA=1 api
#
ARG INSTALL_FACE_EXTRA=0

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_FACE_EXTRA" = "1" ]; then \
        uv sync --frozen --no-install-project --no-dev --extra face; \
    else \
        uv sync --frozen --no-install-project --no-dev; \
    fi


# ── Development ───────────────────────────────────────────────────────────────
# Source is bind-mounted by compose; dev dependencies are included so the test
# suite and linters run inside the container.
FROM base AS development

ARG INSTALL_FACE_EXTRA=0

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_FACE_EXTRA" = "1" ]; then \
        uv sync --frozen --no-install-project --extra face; \
    else \
        uv sync --frozen --no-install-project; \
    fi

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


# ── Production ────────────────────────────────────────────────────────────────
FROM deps AS production

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# Non-root is required by most container platform policies and correct anyway.
RUN useradd --create-home --uid 1000 fvas \
    && chown -R fvas:fvas /app
USER fvas

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# start-period covers model loading (Phase 5). Without it an orchestrator kills
# the container before startup finishes and the deploy never converges.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Models load per worker, so N workers hold N copies of the weights. Two is the
# ceiling on a 2 GB instance; scale horizontally, not by adding workers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
