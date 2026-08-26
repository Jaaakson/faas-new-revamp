.DEFAULT_GOAL := help
COMPOSE := docker compose
API     := $(COMPOSE) exec api

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Environment ───────────────────────────────────────────────────────────────
.PHONY: setup
setup: ## First-time setup: env file, deps, hooks
	@[ -f .env ] || cp .env.example .env
	npm install
	cd apps/api && uv sync

.PHONY: up
up: ## Start the full stack
	$(COMPOSE) up -d

.PHONY: down
down: ## Stop the stack
	$(COMPOSE) down

.PHONY: logs
logs: ## Tail all logs
	$(COMPOSE) logs -f

.PHONY: ps
ps: ## Show service status
	$(COMPOSE) ps

# ── Database ──────────────────────────────────────────────────────────────────
.PHONY: migrate
migrate: ## Apply migrations
	$(API) alembic upgrade head

.PHONY: downgrade
downgrade: ## Roll back one migration
	$(API) alembic downgrade -1

.PHONY: revision
revision: ## Autogenerate a migration: make revision m="add subjects"
	$(API) alembic revision --autogenerate -m "$(m)"

.PHONY: seed
seed: ## Seed the demo tenant
	$(API) python -m app.cli seed

.PHONY: reset-db
reset-db: ## Drop the volume and re-migrate (destroys local data)
	$(COMPOSE) down -v
	$(COMPOSE) up -d postgres redis
	$(COMPOSE) up -d api
	sleep 5
	$(MAKE) migrate

# ── Quality ───────────────────────────────────────────────────────────────────
.PHONY: lint
lint: lint-api lint-web ## Lint everything

.PHONY: lint-api
lint-api:
	cd apps/api && uv run ruff check . && uv run ruff format --check . && uv run mypy app

.PHONY: lint-web
lint-web:
	npm run lint && npm run type-check

.PHONY: fmt
fmt: ## Autofix formatting
	cd apps/api && uv run ruff check --fix . && uv run ruff format .
	npm run format

.PHONY: test
test: test-api test-web ## Run all tests

.PHONY: test-api
test-api:
	cd apps/api && FACE_ENGINE=fake uv run pytest -q

.PHONY: test-web
test-web:
	npm run test

.PHONY: build
build: ## Build the web app
	npm run build

# ── Contract ──────────────────────────────────────────────────────────────────
.PHONY: openapi
openapi: ## Regenerate openapi.json and the shared TypeScript types
	cd apps/api && uv run python -m app.cli export-openapi > ../../openapi.json
	npm run generate --workspace=@fvas/shared

.PHONY: check
check: lint test ## Everything CI runs, locally
