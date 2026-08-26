<div align="center">

---

```http
POST /v1/verifications
Authorization: Bearer fvas_live_9f2c…

{ "subject_id": "sub_01HQZX8K4M2N7P", "image": "<base64 jpeg>" }
```

```json
{ "decision": "verified", "similarity": 0.8121, "confidence": "high",
  "threshold": 0.38, "timing": { "total_ms": 284 } }
```

Deliberately **not** a face-recognition toolkit and **not** an attendance app.
One question, answered honestly.

---

## Table of contents

[What makes it different](#what-makes-it-different) ·
[Features](#features) ·
[Tech stack](#tech-stack) ·
[Requirements](#requirements) ·
[Quick start](#quick-start) ·
[What you should see](#what-you-should-see) ·
[Environment variables](#environment-variables) ·
[Repository layout](#repository-layout) ·
[Local development](#local-development) ·
[Database](#database) ·
[Testing](#testing) ·
[Production build](#production-build) ·
[Troubleshooting](#troubleshooting) ·
[Workflow](#development-workflow) ·
[Documentation](#documentation) ·
[Limitations](#status-and-honest-limitations) ·
[License](#license)

---

## What makes it different

**The outcome is three-way, never two.** `rejected` means "a real face, but not
this person". `inconclusive` means "I could not decide" — no face, too dark,
liveness failed, not enrolled. Collapsing the second into the first tells someone
in a dark room that they are an impostor, and fills the customer's fraud metrics
with lighting problems.

**A decision carries its threshold.** `threshold_applied` is written onto every
session row, so changing the threshold next month cannot rewrite what happened
this month.

**Biometric deletion is physical.** `face_templates` has no `deleted_at` column.
A soft-deleted biometric template is still retained biometric data.

**The numbers are measured, and the gaps are stated just as loudly.** FAR/FRR
come from a calibration run on 8,559 genuine and 500,000 impostor pairs. What was
*not* measured has its own section in the [model card](docs/16-model-card.md).

---

## Features

| Area                    | What works                                                                                                                                           |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Enrollment**    | Multi-shot capture, 8 quality gates with per-gate scores, duplicate detection over pgvector, versioned profiles that supersede rather than overwrite |
| **Verification**  | Three-way outcome, confidence bands, per-request threshold that can tighten but never loosen, full timing breakdown                                  |
| **Capture UI**    | Live exposure/focus/steadiness meters, auto-capture, pose prompts, camera-permission recovery, upload fallback                                       |
| **Auth**          | JWT sessions with refresh rotation and reuse detection, Argon2id passwords, account lockout, 4-role RBAC                                             |
| **API keys**      | Reveal-once secrets, scopes, rotation with 24 h overlap, immediate revocation, optional CIDR allowlist                                               |
| **Multi-tenancy** | Repository-level scoping, generated cross-tenant tests, PostgreSQL row-level security                                                                |
| **Webhooks**      | HMAC-SHA256 signing, at-least-once delivery with backoff, delivery log                                                                               |
| **Operations**    | Quota metering, rate limiting, idempotency, audit trail, retention job, tested backup/restore                                                        |

---

## Tech stack

**Frontend** — Next.js 15 (App Router), React 19, TypeScript, Tailwind v4,
shadcn/ui, TanStack Query, Recharts, nuqs, Motion, Zod, React Hook Form.

**Backend** — Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2,
PostgreSQL 16 + pgvector, Redis.

**Face pipeline** — InsightFace (SCRFD-10GF + ArcFace R50) on ONNX Runtime,
behind a `FaceEngine` protocol with a deterministic fake for tests.

**Tooling** — Docker Compose, uv, ruff, mypy, pytest, Vitest, GitHub Actions.

---

## Requirements

|                                 | Minimum | Notes                                         |
| ------------------------------- | ------- | --------------------------------------------- |
| Docker Desktop                  | 24+     | The only hard requirement for the quick start |
| RAM for Docker                  | 4 GB    | 8 GB with the real face engine                |
| Free disk                       | ~3 GB   | ~4 GB with the face models                    |
| Node.js                         | 22+     | Only to run the web app outside Docker        |
| [uv](https://docs.astral.sh/uv/) | latest  | Only to run the API outside Docker            |

Ports `3000`, `8000`, `5432`, `6379` must be free — or change them, see
[environment variables](#environment-variables).

---

## Quick start

Five commands. Nothing else to configure.

```bash
git clone <repository-url> fvas && cd fvas
cp .env.example .env
docker compose up -d --wait
docker compose exec api alembic upgrade head
docker compose exec api python -m app.cli seed
```

Open **http://localhost:3000** and sign in:

| Email                           | Password             | Role      |
| ------------------------------- | -------------------- | --------- |
| `owner@acme.example.com`      | `Password123!demo` | Owner     |
| `admin@acme.example.com`      | `Password123!demo` | Admin     |
| `dev@acme.example.com`        | `Password123!demo` | Developer |
| `compliance@acme.example.com` | `Password123!demo` | Viewer    |

> Start as **Owner** for the full tour. The other three exist so you can see what
> RBAC actually does — a Viewer cannot enroll, a Developer cannot delete
> biometric data.

`--wait` blocks until every service reports healthy, so if the command returns,
the stack really is up.

**First run takes 3–5 minutes** — two images build, Postgres and Redis pull.
Later starts take seconds.

### Verify it worked

```bash
cd apps/api && uv run python ../../scripts/smoke_test.py
```

Twelve checks over the real product loop — create a subject, enroll, verify,
reject a different face, revoke a key. All green means everything is wired
correctly.

| Service                  | URL                        |
| ------------------------ | -------------------------- |
| Console + marketing site | http://localhost:3000      |
| API                      | http://localhost:8000      |
| Swagger UI               | http://localhost:8000/docs |

---

## What you should see

After seeding: one organization, 25 subjects, 22 enrolled face profiles, ~1,300
verification sessions across 30 days.

| Page                    | What it shows                                                                 |
| ----------------------- | ----------------------------------------------------------------------------- |
| **Overview**      | Volume, success rate, p95 latency, recent verifications                       |
| **Analytics**     | Outcome split, failure reasons, latency histogram, hourly success heatmap     |
| **Subjects**      | The list, plus a detail page with profile history and enrollment attempts     |
| **Verifications** | Every decision with similarity, threshold and timing                          |
| **Verify**        | A live camera page — enroll yourself, then verify                            |
| **API keys**      | Create one and watch the reveal-once dialog refuse to close until you copy it |
| **Logs**          | The append-only audit trail                                                   |

The seed data is deliberately imperfect — a weekday/weekend rhythm, a night-shift
dip, a two-day anomaly — because uniformly random data produces flat charts that
teach nobody how to read the dashboard.

---

## Environment variables

`cp .env.example .env` gives working local defaults, and every variable is
documented inline there. These are the ones you may need to change.

| Variable                  | Default  | Change it when                                                                                               |
| ------------------------- | -------- | ------------------------------------------------------------------------------------------------------------ |
| `WEB_PORT`              | `3000` | Port taken                                                                                                   |
| `API_PORT`              | `8000` | Port taken                                                                                                   |
| `POSTGRES_PORT`         | `5432` | You have PostgreSQL installed locally — the most common conflict                                            |
| `REDIS_PORT`            | `6379` | You have Redis installed locally                                                                             |
| `FACE_ENGINE`           | `fake` | You want the real ONNX pipeline                                                                              |
| `ONNX_INTRA_OP_THREADS` | `2`    | **Never 0.** A container sees the host's core count regardless of its CPU quota; 0 measured 5× slower |

`DATABASE_URL` and `REDIS_URL` are **host-oriented** — used by anything you run
outside Docker (alembic, pytest, a native uvicorn). Compose overrides them with
service names for the containers. If you change `POSTGRES_PORT`, change the port
inside `DATABASE_URL` to match.

### The face engine

Ships as `FACE_ENGINE=fake`: deterministic, no model download, and what the whole
test suite runs against. That default is why a clean clone works immediately.

`fake` accepts every face — the application **refuses to start** with it set in a
production environment.

For the real pipeline see
[Docker setup §11](docs/13-docker-setup.md#11-switching-on-the-real-face-engine).
It needs a build arg, a ~600 MB model download, and 8 GB of RAM.

---

## Repository layout

```
apps/
  api/                    FastAPI service
    app/
      core/               config, security, plans, rate limiting, tenancy
      modules/            one folder per bounded context
        auth/             registration, login, tokens
        identity/         organizations, members, API keys
        biometrics/       subjects, enrollment, verification, the face engine
        webhooks/         signing and delivery
        analytics/        rollups and reporting
        platform/         health, seed, retention
      shared/             base model, base repository, shared schemas
      dependencies/       FastAPI dependency providers
    alembic/versions/     numbered, linear migrations
    tests/                392 tests, run on SQLite and PostgreSQL
  web/                    Next.js console and marketing site
    src/
      app/                routes: (marketing), (auth), (console)
      components/         ui/ primitives, console/, marketing/, docs/
      features/           per-domain API hooks and types
      lib/                api client, formatting, frame analysis
      hooks/              reusable React hooks
      stores/             Zustand state
packages/shared/          TypeScript types generated from the OpenAPI schema
docs/                     18 documents: PRD through model card
scripts/                  smoke test, load test, backup/restore, deploy
spikes/                   Phase 0 latency and threshold calibration
```

Each module owns its models, schemas, repositories, service and router.
Repositories are private to their module — cross-module access goes through the
other module's *service*, never its repository.

---

## Local development

Everything runs in Docker with hot reload. `make help` lists every task.

```bash
make up      # start
make logs    # tail everything
make ps      # service status
make down    # stop
```

### Outside Docker

Databases still come from Compose; the apps run natively for faster reloads and a
normal debugger.

```bash
docker compose up -d postgres redis

cd apps/api && uv sync && uv run uvicorn app.main:app --reload   # API
npm install && npm run dev                                        # web
```

---

## Database

```bash
make migrate                     # apply migrations
make revision m="add widgets"    # autogenerate one
make seed                        # seed the demo tenant
make reset-db                    # destroy the volume and start over
docker compose exec api python -m app.cli retention --dry-run
```

Migrations are numbered and linear (`0001`…`0009`). CI runs `alembic check` on
every push, so a model change without a matching migration fails the build rather
than passing tests and breaking production.

### Backups

```bash
./scripts/backup.sh dump
./scripts/backup.sh restore backups/fvas-<timestamp>.dump
./scripts/backup.sh restore-drill    # backs up, destroys, restores, verifies
```

`restore-drill` truncates the database and checks that the restore reproduced it
exactly, checksum included. An untested backup is a hypothesis.

---

## Testing

```bash
make test     # API + web
make check    # everything CI runs
```

```bash
cd apps/api
uv run pytest -q                                   # ~2 min, SQLite
uv run pytest --cov=app --cov-report=term-missing  # coverage, gate at 80%

TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/fvas_test \
  uv run pytest -q                                 # fidelity run
```

The suite runs against **both** SQLite (fast, every push) and PostgreSQL
(catches what SQLite cannot model: JSONB, partial indexes, pgvector, RLS).

```bash
cd apps/web && npx vitest run && npx tsc --noEmit
```

---

## Production build

```bash
cd apps/api && docker build --target production -t fvas-api:prod .
cd apps/web && npm run build
```

The API production image is non-root, ships no dev dependencies, tests or `.env`
files, and has a healthcheck whose start period covers model loading. Deployment
is in the [runbook](docs/17-deployment-runbook.md), which is explicit about which
steps have actually been executed and which have not.

---

## Troubleshooting

<details>
<summary><strong>Bind for 0.0.0.0:5432 failed: port is already allocated</strong></summary>

A locally installed PostgreSQL owns the port. In `.env`:

```bash
POSTGRES_PORT=15432
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:15432/fvas
```

Both lines must agree. Then `docker compose up -d`.

</details>

<details>
<summary><strong>password authentication failed for user "postgres"</strong></summary>

Usually the same problem in disguise — you are talking to a *different*
PostgreSQL that happens to own 5432. Check with `docker compose port postgres 5432`.

</details>

<details>
<summary><strong>relation "users" does not exist</strong></summary>

Migrations have not run: `docker compose exec api alembic upgrade head`

</details>

<details>
<summary><strong>ModuleNotFoundError for a package you just added</strong></summary>

The API keeps its virtualenv in an anonymous volume and Docker reuses it across
rebuilds, so the new image's venv is shadowed by the old one:

```bash
docker compose up -d --build --force-recreate --renew-anon-volumes api
```

</details>

<details>
<summary><strong>The dashboard is empty</strong></summary>

You skipped the seed: `docker compose exec api python -m app.cli seed`

</details>

<details>
<summary><strong>TLS handshake timeout during the first build</strong></summary>

A Docker Hub flake, not your setup. Run `docker compose up -d --build` again.

</details>

<details>
<summary><strong>The camera does not work</strong></summary>

Browsers expose it only over HTTPS or on `localhost` — a LAN address like
`192.168.1.5:3000` will not work. If you denied permission once, the browser
remembers; reset it via the padlock in the address bar. The enrollment wizard
detects this and offers photo upload instead.

</details>

<details>
<summary><strong>The API restarts in a loop</strong></summary>

```bash
docker compose logs api | tail -30
```

Configuration is validated at startup and the process exits on anything invalid,
so the reason is always in the log rather than hidden behind broken requests.

</details>

More: [docs/13-docker-setup.md](docs/13-docker-setup.md).

---

## Development workflow

```bash
make fmt      # autofix formatting
make lint     # ruff + mypy + eslint
make test
make check    # everything CI runs, before you push
```

Conventional commits are enforced by commitlint. After changing an API response
model, regenerate the contract:

```bash
make openapi
```

CI fails if `openapi.json` or the generated TypeScript types drift from the
backend, so a schema change that breaks the frontend surfaces as a type error
rather than a runtime bug.

---

## Documentation

`docs/` is the blueprint — written before the code, and kept honest against it.

|                                                          |                                                         |
| -------------------------------------------------------- | ------------------------------------------------------- |
| [01 — PRD](docs/01-prd.md)                               | Problem, personas, scope, pricing                       |
| [05 — Architecture](docs/05-architecture.md)             | Modular monolith, layering, the`FaceEngine` seam      |
| [06 — Database](docs/06-database.md)                     | Schema, with the reasoning behind each choice           |
| [07 — API design](docs/07-api-design.md)                 | Conventions, errors, the public surface                 |
| [08 — AI workflow](docs/08-ai-workflow.md)               | Pipeline, thresholds, liveness limits                   |
| [09 — Security](docs/09-security.md)                     | Trust model, RBAC, retention                            |
| [13 — Docker setup](docs/13-docker-setup.md)             | Step by step, including every failure hit along the way |
| [14 — Phase 0 spike](docs/14-phase-0-spike.md)           | Latency and threshold measurements                      |
| [15 — Security audit](docs/15-security-audit.md)         | Findings, each with a disposition                       |
| [16 — Model card](docs/16-model-card.md)                 | Measured accuracy, and what was not measured            |
| [17 — Deployment runbook](docs/17-deployment-runbook.md) | What to run, and what to do when it breaks              |
| [18 — Demo script](docs/18-demo-script.md)               | A three-minute walkthrough                              |

---

## Status and honest limitations

**Local-demo-ready MVP.** It runs end to end, the tests are real, the
measurements are measurements. It has never been deployed.

What it is **not**:

- **No certified liveness detection.** The shipped presentation-attack checks are
  three cheap heuristics. They stop a face on a phone screen and a low-quality
  print. They do not stop a good screen at the right angle, a prepared video, or
  a mask. Appropriate as a step-up factor where the attacker also needs the
  account and the device; **not** appropriate as the sole control for
  unsupervised remote onboarding.
- **Accuracy is measured on LFW only.** No per-slice results by skin tone, age or
  gender presentation — LFW cannot support them. Treat the figures as an upper
  bound for any population unlike it.
- **The face models are licensed for non-commercial research use.** A commercial
  deployment needs a different model; the `FaceEngine` protocol exists so that is
  one adapter, not a rewrite.
- **Never deployed.** No cloud account, domain or registry. The release pipeline
  is written and its YAML validates, but it has never run.
- **RLS is inert in development**, because the local stack connects as a
  superuser. Production must use the `fvas_app` role created by migration 0009.

Per-phase status: [docs/10-roadmap.md](docs/10-roadmap.md).

---

## License

MIT — see [LICENSE](LICENSE).

The InsightFace model weights are **not** covered by this license and are
published for non-commercial research use only.
