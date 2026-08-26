# Contributing to Fvas

Thanks for taking the time. This document covers the setup, the workflow, and the standards a change has to meet.

The full engineering standards live in [docs/12-repository-standards.md](docs/12-repository-standards.md). This is the short version.

---

## Setup

**Prerequisites:** Docker + Docker Compose, Node 22+, Python 3.12+, Git.

```bash
git clone https://github.com/<you>/fvas.git && cd fvas
cp .env.example .env
docker compose up -d
docker compose exec api alembic upgrade head
docker compose exec api python -m app.cli seed
```

| Service | URL |
| --- | --- |
| Web | http://localhost:3000 |
| API | http://localhost:8000 |
| Swagger | http://localhost:8000/docs |

Seeded login: `owner@acme.test` / `Password123!`

Install the git hooks once:

```bash
npm install && npm run prepare
```

## Workflow

1. Open or claim an issue — discussion before implementation saves rework
2. Branch off `develop`: `feat/short-description`
3. Commit using [Conventional Commits](https://www.conventionalcommits.org/) — enforced by a hook
4. Push and open a PR into `develop`, filling in the template
5. CI must be green and one review must approve
6. Squash-merge; the branch is deleted automatically

## Standards

**Commits**

```
feat(biometrics): add duplicate detection at enrollment
fix(web): restore camera stream after tab visibility change
docs(api): document the idempotency contract
```

Types: `feat` `fix` `docs` `style` `refactor` `perf` `test` `build` `ci` `chore`
Scopes: `api` `web` `db` `auth` `biometrics` `docs` `infra` `deps`

**Code style** is decided by tooling, not by review — `ruff` for Python, ESLint + Prettier for TypeScript, both on a pre-commit hook. Don't spend review time on formatting.

**Tests** — new endpoints need integration tests covering the failure paths, not only the happy one. New services need unit tests. Run `FACE_ENGINE=fake` locally; it's what CI uses and it skips the model download.

```bash
make test          # everything
make test-api      # pytest
make test-web      # vitest
make test-e2e      # playwright
make lint          # all linters
make fmt           # autofix
```

## Before you open a PR

- [ ] Keep it under ~400 changed lines — split larger work into a stack
- [ ] All four UI states implemented: loading, empty, error, success
- [ ] Every tenant-scoped query is actually scoped by `organization_id`
- [ ] Authorization enforced on the server, not only in the UI
- [ ] New endpoints documented in OpenAPI with a working example
- [ ] Migration is reversible (`alembic downgrade` tested)
- [ ] No secrets, PII, embeddings, or image bytes in logs
- [ ] Screenshots or a recording for any UI change
- [ ] Docs updated in the same PR if the change touches an API contract, the schema, or a security control

## Areas that need extra care

**Biometric data.** Templates are irrevocable — a person cannot change their face. Deletion must be physical, never a soft-delete flag. Embeddings must never appear in logs, error messages, or API responses. If a change touches `face_templates`, say so explicitly in the PR description.

**Tenant isolation.** Every tenant query goes through `TenantScopedRepository`. If you find yourself writing a raw query against a tenant table, that's the signal to stop and ask.

**Thresholds.** Don't change a default threshold without a calibration run and the resulting curve attached to the PR. The numbers in the config are measurements, not preferences.

## Reporting security issues

**Do not open a public issue.** Email `security@fvas.io` with reproduction steps and impact. You'll get an acknowledgement within 48 hours.

## Questions

Open a [Discussion](../../discussions) or comment on the relevant issue. Questions about *why* something is designed a way it is are usually answered somewhere in [`docs/`](docs/) — and if they aren't, that's a documentation bug worth filing.
