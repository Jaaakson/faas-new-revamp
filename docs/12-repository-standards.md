# 12 — Repository Standards

How the repository is organized, how changes get in, and what "done" means for a commit.

---

## 1. Repository shape

```
fvas/
├── .github/
│   ├── workflows/          ci.yml · deploy-staging.yml · deploy-production.yml
│   ├── ISSUE_TEMPLATE/     bug_report.yml · feature_request.yml · config.yml
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── dependabot.yml
├── apps/
│   ├── api/                FastAPI modular monolith
│   └── web/                Next.js
├── packages/
│   └── shared/             Types generated from OpenAPI
├── docs/                   The blueprint — this directory
├── infra/
│   ├── docker/             Dockerfiles
│   └── compose/            Environment-specific compose overrides
├── scripts/                Setup, seed, calibration, release helpers
├── .env.example
├── CONTRIBUTING.md · LICENSE · Makefile · docker-compose.yml · README.md
```

**Monorepo, npm workspaces.** A polyrepo would force a contract change (schema + backend + frontend) across three PRs that can merge out of order and break `main` in between. Turborepo/Nx were considered and rejected for now: the caching wins matter at a scale this project doesn't have, and they add configuration surface. If build times exceed ~5 minutes, revisit.

## 2. Branching

`main` is always deployable. `develop` is the integration branch. Work happens on short-lived branches:

```
feat/verification-endpoint
fix/camera-permission-safari
docs/api-reference
chore/bump-fastapi
refactor/extract-face-engine
```

**Protection on `main` and `develop`:** PR required, CI green required, one approving review, no force-push, branches deleted on merge. Squash-merge to `main` so history is one commit per change; the PR retains the detail.

Trunk-based development with feature flags would suit a larger team better. At one to three developers, short-lived branches off `develop` give enough isolation without the flag infrastructure.

## 3. Commits

**Conventional Commits**, enforced by `commitlint` in a `commit-msg` hook and re-checked in CI.

```
<type>(<scope>): <subject>

[body]
[footer]
```

| Type | Use |
| --- | --- |
| `feat` | A new capability |
| `fix` | A bug fix |
| `docs` | Documentation only |
| `style` | Formatting, no behavior change |
| `refactor` | Restructure without behavior change |
| `perf` | Performance |
| `test` | Tests |
| `build` | Build system, dependencies |
| `ci` | Pipeline |
| `chore` | Everything else |

Scopes: `api`, `web`, `db`, `auth`, `biometrics`, `docs`, `infra`, `deps`.

```
feat(biometrics): add duplicate face detection at enrollment

Search existing templates within the tenant using pgvector HNSW before
creating a profile. Returns 409 with the matched subject and similarity
so the caller can decide deliberately rather than silently double-enrolling.

Threshold defaults to 0.6 — higher than the match threshold, because a
false positive here blocks a legitimate user.

Closes #42
```

Breaking changes use `feat(api)!:` and a `BREAKING CHANGE:` footer. The subject line is imperative mood, lowercase, no trailing period, ≤ 72 characters.

This is not ceremony: conventional commits are what let the changelog be generated, let `main`'s history be readable a year later, and let a reviewer know the blast radius before opening the diff.

## 4. Pull requests

Requirements: linked issue, filled template, CI green, self-review completed first, screenshots or a recording for any UI change, and a migration plan noted if the change touches the schema.

**Size** — target under 400 changed lines. Review quality falls off a cliff past that, and a 2,000-line PR gets rubber-stamped. Large features ship as a stack of small PRs behind a flag or an unrouted page.

**Review checklist:**

- [ ] Does it do what the issue asked, and nothing else?
- [ ] Is every tenant-scoped query actually scoped?
- [ ] Is authorization enforced server-side, not only in the UI?
- [ ] Are loading, empty, error, and success states all implemented?
- [ ] Are new endpoints documented in OpenAPI with examples?
- [ ] Do the tests cover the failure paths, not just the happy one?
- [ ] Any secrets, PII, embeddings, or image bytes in logs?
- [ ] Is the migration reversible?
- [ ] Keyboard-navigable, labelled, sufficient contrast?

## 5. Code style

| | Tooling | Enforcement |
| --- | --- | --- |
| **Python** | `ruff` (lint + format), `mypy --strict` on `app/`, line length 100, Google docstrings on public functions | Pre-commit + CI |
| **TypeScript** | ESLint (`next/core-web-vitals` + `jsx-a11y`), Prettier, `strict: true`, no `any` without a comment justifying it | Pre-commit + CI |
| **SQL** | Migrations only through Alembic; no raw DDL outside a revision | Review |
| **Commits** | `commitlint` | Hook + CI |
| **Secrets** | `gitleaks` | CI |

Formatting is never a review topic. It is decided by a tool, applied on commit, and checked in CI. Time spent debating a line break is time not spent on the tenant-scoping question above it.

**Naming** — Python `snake_case` / `PascalCase` classes; TypeScript `camelCase` / `PascalCase` components / `SCREAMING_SNAKE` constants; files `kebab-case.ts` except React components which are `PascalCase.tsx`; database `snake_case`, plural tables.

## 6. Testing policy

| Level | Scope | Tooling | Bar |
| --- | --- | --- | --- |
| Unit | Services, engine, utilities, pure logic | `pytest`, `vitest` | ≥ 70% on services and repositories |
| Integration | Endpoints against a real Postgres + Redis | `pytest` + `httpx` | Every endpoint, happy + failure paths |
| Contract | OpenAPI ↔ generated TS types | CI diff | No drift |
| E2E | Register → onboard → enroll → verify → audit | Playwright | The critical path, on every PR |
| Security | Tenant isolation, RBAC matrix | Generated `pytest` suites | Every list/get endpoint, every role |
| A11y | `axe` assertions in E2E | `@axe-core/playwright` | Zero critical violations |

**Two suites are generated rather than hand-written:** tenant isolation and the RBAC matrix. Both are exhaustive by nature, and a hand-written version silently fails to cover the endpoint someone added last Tuesday. Generating them from the route table means new endpoints are covered by default — which is the only way this kind of check stays true over time.

Coverage is a floor, not a goal. 100% coverage of getters proves nothing; the tests that matter are the ones asserting a rejected verification is logged, a cross-tenant read 404s, and the last Owner can't be removed.

## 7. Documentation as a deliverable

`docs/` is versioned with the code and reviewed like the code. A PR that changes an API contract, a schema, or a security control **must** update the corresponding document in the same PR. Documentation that lags the implementation is worse than none, because people trust it.

Everything else stays current automatically or not at all: OpenAPI generates from the code, the ERD generates from the models, TS types generate from OpenAPI, and the changelog generates from commits. **Anything a human has to remember to update, eventually won't be.**

## 8. Issue management

Labels: `type:` bug / feature / docs / chore · `area:` api / web / db / biometrics / infra · `priority:` p0–p3 · `status:` needs-triage / ready / blocked · plus `good-first-issue`.

Bug reports require reproduction steps, expected vs actual, environment, and the `request_id` if the API was involved — that ID resolves most reports in one query instead of a conversation.

## 9. Release process

Semantic versioning on the public API surface. Tagged releases from `main`, changelog generated from conventional commits, release notes call out breaking changes, migrations, and new environment variables at the top.

**Deprecation policy for the public API:** announce in the changelog and via email → serve a `Sunset` header and a deprecation warning in the response → minimum 12 months → remove. A platform whose customers can't trust the endpoints to keep working is not a platform.

---

**Back to:** [Documentation index](../README.md#documentation)
