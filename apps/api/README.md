# Fvas API

FastAPI modular monolith serving both API surfaces:

| Surface | Prefix | Auth |
| --- | --- | --- |
| Public API | `/v1` | API key — `Authorization: Bearer fvas_live_…` |
| Console API | `/v1/console` | JWT |
| Platform probes | `/health`, `/ready` | none |

Design rationale lives in [`docs/05-architecture.md`](../../docs/05-architecture.md).

## Running

From the repository root, the full stack:

```bash
docker compose up -d
```

Or just the API, against your own Postgres and Redis:

```bash
uv sync
uv run uvicorn app.main:app --reload
```

| | |
| --- | --- |
| API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |

## Layout

```
app/
├── main.py            app factory — middleware order, routers, lifespan
├── cli.py             export-openapi · check-config · check-health · seed
├── core/              config, database, redis, logging, exceptions, context
├── middleware/        request-id, access log, security headers
├── dependencies/      shared FastAPI dependencies
├── shared/            base model, tenant-scoped repository, utils
└── modules/           one package per domain
    └── platform/      health and readiness
```

**Layer rules** — routers never contain business logic or touch the ORM;
services own the transaction and know nothing about HTTP; repositories are
private to their module and never commit. Cross-module access goes through the
other module's *service*, never its repository.

## Commands

```bash
uv run pytest                      # test suite (SQLite, no services needed)
uv run pytest --cov=app            # with coverage
uv run ruff check . && uv run ruff format .
uv run mypy app                    # strict
uv run alembic upgrade head        # apply migrations
uv run alembic downgrade base      # roll all the way back
uv run alembic revision --autogenerate -m "add subjects"
uv run python -m app.cli check-config
uv run python -m app.cli export-openapi > ../../openapi.json
```

## Adding a module

1. Create `app/modules/<name>/` with `router.py`, `service.py`, `repository.py`, `schemas.py`, `models.py`
2. Tenant-owned repositories subclass `TenantScopedRepository` — never build a
   query outside `_scoped()`
3. Import the models in `alembic/env.py`, or autogenerate will not see them
4. Mount the router in `app.main.create_app()` under `settings.API_V1_PREFIX`
5. Add integration tests covering the failure paths, not just the happy one

## Testing note

The suite runs against in-memory SQLite so `pytest` needs no running services
and finishes in under a second. That holds while Phase 1 defines no tables.
From Phase 3, integration tests move to a Postgres service container — SQLite
cannot honestly test partial unique indexes, `citext`, or pgvector operations.

`FACE_ENGINE=fake` (Phase 5 onward) keeps CI free of the ~350 MB model download.
