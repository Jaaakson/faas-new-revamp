# 17 — Deployment runbook

What to run, in what order, and what to do when it goes wrong.

> **Status.** The pipeline, images, smoke test, backup and restore tooling are
> built and — except where noted — executed. **Nothing has been deployed to a
> real host**: no cloud account, registry, domain or managed database exists for
> this project. Every step below is marked with whether it has actually run.
> [10 — Roadmap](10-roadmap.md) carries the same distinction in the Phase 9
> definition of done.

---

## 1. What has and has not been verified

| Item | Verified? |
| --- | --- |
| Production image builds, non-root, no dev deps, no tests or `.env` shipped | ✅ built and inspected inside the running container |
| Production image boots against real Postgres + Redis and reports healthy | ✅ `Up (healthy)`, `/health` 200 |
| Production refuses to start with a fake face engine | ✅ container exited with the guard's message |
| Security headers, including HSTS in production only | ✅ measured on real responses |
| Smoke test gates the product loop | ✅ 12/12 against the running stack |
| Backup, destroy, restore, verify | ✅ **drill executed** — see §4 |
| Release workflow YAML | ✅ parses; jobs resolve |
| Deploy verbs (`current` / `release` / `rollback`) | ⚠️ rehearsed against the `noop` target only |
| Actual deploy to a host | ❌ **never run** |
| Automatic deploy on merge to `main` | ❌ **never run** |
| Alerts fired deliberately | ❌ no alerting backend configured |
| HTTPS with valid certificates | ❌ no domain |

---

## 2. Topology

```
                  ┌──────────────┐
   browser ─────► │ Vercel (web) │ ── BFF routes ──┐
                  └──────────────┘                 │
                                                   ▼
   customer backend ─── API key ──────────► ┌─────────────┐
                                            │  API (2×)   │
                                            └──────┬──────┘
                                                   │
                                    ┌──────────────┴──────────────┐
                                    ▼                             ▼
                          ┌──────────────────┐        ┌────────────────────┐
                          │ Postgres+pgvector│        │ Redis              │
                          │ (managed)        │        │ rate limit, idem.  │
                          └──────────────────┘        └────────────────────┘
```

**Two workers, not more.** Each holds its own copy of the ONNX weights, so
workers multiply memory rather than share it. Scale horizontally.

---

## 3. Deploying

### Automatic

Merge to `main`. `release.yml` runs: CI → build → **backup** → migrate →
`alembic check` → deploy → smoke test → roll back on failure → re-smoke the
rollback.

### Manual

```bash
gh workflow run release.yml -f environment=production
```

### Required configuration

| Secret | Purpose |
| --- | --- |
| `DATABASE_URL_ADMIN` | Owner role. Migrations only |
| `DEPLOY_TOKEN` | Host API credential |
| `SMOKE_EMAIL` / `SMOKE_PASSWORD` | Smoke-test account, minimum privileges |

| Variable | Purpose |
| --- | --- |
| `API_BASE_URL`, `WEB_BASE_URL` | Smoke-test targets |

The **application** connects as `fvas_app`, never the admin role. That
separation is what makes row-level security effective — see
[15 — Security audit §2](15-security-audit.md).

### Environment for the API container

```bash
ENVIRONMENT=production
DEBUG=false
COOKIE_SECURE=true
DATABASE_URL=postgresql+asyncpg://fvas_app:...@host:5432/fvas   # NOT the owner
REDIS_URL=redis://...
JWT_SECRET_KEY=<32+ bytes>
CORS_ORIGINS=https://app.fvas.io                                 # https, no wildcard
FACE_ENGINE=insightface                                          # `fake` refuses to boot
ONNX_INTRA_OP_THREADS=2                                          # never 0
SENTRY_DSN=<optional>
```

`assert_production_safe()` refuses to start on `DEBUG=true`, a short JWT secret,
`COOKIE_SECURE=false`, or a plaintext CORS origin. A misconfigured deploy dies
in its first second rather than serving broken requests for an hour.

---

## 4. Backups

```bash
./scripts/backup.sh dump            # timestamped custom-format dump
./scripts/backup.sh restore <file>
./scripts/backup.sh restore-drill   # dump, destroy, restore, verify
./scripts/backup.sh prune
```

### The drill has been run

Executed 2026-08-01 against the running stack. It is not a dry run — it
truncates.

```
1. fingerprint live     1,4,29,25,66,1731,19,0bf1c013…
2. back up              backups/fvas-20260801T140524Z.dump
3. TRUNCATE … CASCADE   0,0,0,0,0,0,0,none
4. restore
5. compare              1,4,29,25,66,1731,19,0bf1c013…

PASS — destroyed and fully recovered
```

The fingerprint covers organizations, users, subjects, profiles, templates,
verification sessions, audit entries, and an `md5` over subject ids — so a
restore that returned the right *counts* with the wrong *rows* would still fail.

**Run this quarterly.** A backup nobody has restored is a hypothesis.

---

## 5. When a deploy fails

The pipeline rolls back automatically and re-runs the smoke test against the
restored revision. If that also fails, or you are doing it by hand:

```bash
DEPLOY_TARGET=fly ./scripts/deploy.sh rollback <previous-image-ref>

cd apps/api && uv run python ../../scripts/smoke_test.py \
  --base https://api.fvas.io --expect-engine insightface
```

**Migrations do not roll back automatically, and that is deliberate.** An
automatic `alembic downgrade` during an incident can destroy data the new schema
already wrote. The pre-migration backup is the recovery path; use it knowingly.

### Triage

| Symptom | Look at |
| --- | --- |
| Container starts then exits | `assert_production_safe`, or the fake-engine guard — both log the exact reason |
| Healthy but every verification is `inconclusive` | Models missing from the image; `/health` reports `face_engine` |
| 401 on every API-key call | Key revoked, expired, or past its rotation overlap |
| Rising `inconclusive` rate | Capture environment, not the service. Check the quality gates in the response |
| 429 with `Retry-After` in days | Monthly quota, not the rate limiter |
| Cross-tenant data visible | Should be impossible; confirm the app connects as `fvas_app`, not the owner |

---

## 6. Routine operations

```bash
# Nightly — retention
docker compose exec api python -m app.cli retention

# Preview first
docker compose exec api python -m app.cli retention --dry-run

# Verify configuration without starting the server
docker compose exec api python -m app.cli check-config

# Probe dependencies
docker compose exec api python -m app.cli check-health
```

---

## 7. Observability

`SENTRY_DSN` enables error reporting on both apps; unset, both run without it
rather than failing. Structured JSON logs go to stdout with a `request_id` on
every line, correlated with the `X-Request-ID` response header.

**No alerting backend is configured**, so the DoD item "alerts verified by
deliberately triggering one" is **not met**. The signals worth alerting on, when
one exists:

| Signal | Why |
| --- | --- |
| 5xx rate | The only unambiguous "we are broken" |
| p95 latency > 800 ms | The budget the product is sold on |
| `inconclusive` rate step change | Capture environment degraded |
| Quota at 80% / 100% | Already emitted as an event |
| Failed webhook deliveries rising | A customer integration is down |
