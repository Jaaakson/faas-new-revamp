# 13 — Docker Setup Guide

From a clean clone to a running stack with realistic data.

Everything here has been executed on Windows 11 with Docker Desktop, and the
troubleshooting section covers the problems that actually came up rather than
hypothetical ones.

---

## 1. What you need

| | Minimum | Notes |
| --- | --- | --- |
| Docker Desktop | 4.x (Engine 29+) | Must be **running** — the CLI exists without the daemon and every command fails with a confusing pipe error |
| Disk | ~4 GB | Images, Postgres volume, npm and uv caches |
| RAM allocated to Docker | 4 GB | 8 GB once the face models arrive in Phase 5 |

Node and Python are **not** required to run the stack — only to develop outside
the containers.

Verify the daemon before anything else:

```bash
docker info --format '{{.ServerVersion}}'
```

If that errors, start Docker Desktop and wait for the whale icon to settle.

## 2. First run

```bash
git clone https://github.com/<you>/fvas.git && cd fvas
cp .env.example .env
```

Generate a real JWT secret — the placeholder in `.env.example` is deliberately
too short, and the API refuses to start in production without a proper one:

```bash
docker run --rm alpine sh -c "head -c32 /dev/urandom | od -An -tx1 | tr -d ' \n'"
```

Paste the result into `JWT_SECRET_KEY` in `.env`.

Then bring everything up:

```bash
docker compose up -d
```

The first build takes a few minutes: it installs Python and Node dependencies
from scratch. Later builds reuse the cached layers.

<a id="port-conflicts"></a>
> **If Postgres fails to start, or the API reports an authentication error, skip
> to [§7 Port conflicts](#7-port-conflicts) first.** It is by far the most
> common problem and the symptom is misleading.

## 3. Create the schema and seed data

```bash
docker compose exec api alembic upgrade head
docker compose exec api python -m app.cli seed
```

The seed prints the demo credentials:

```
owner@acme.example.com        owner       Rani Wulandari
admin@acme.example.com        admin       Adit Pratama
dev@acme.example.com          developer   Bagas Nugroho
compliance@acme.example.com   viewer      Sari Handayani

Password: Password123!demo
```

Sign in as each to see how the console changes with role — the Viewer account
is what a compliance officer would actually be given.

It creates one organization, 25 subjects, and roughly 1,300 verifications spread
over 30 days with a weekend rhythm, a night-shift dip in success rate, and a
deliberate two-day incident. That shape is the point: uniformly random data
produces flat charts that teach nobody how to read the dashboard.

Re-running is a no-op. To regenerate:

```bash
docker compose exec api python -m app.cli seed --reset
```

## 4. Check it worked

| Service | URL |
| --- | --- |
| Web | http://localhost:3000 |
| Console | http://localhost:3000/dashboard |
| API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |

```bash
docker compose ps                       # all four healthy
curl http://localhost:8000/health       # {"status":"ok",...}
curl http://localhost:8000/ready        # database and redis both true
```

`/ready` is the meaningful one — it reports each dependency separately, so a
`degraded` response tells you *which* service is unreachable.

## 5. Day-to-day

```bash
docker compose up -d              # start
docker compose down               # stop, keep data
docker compose down -v            # stop and DESTROY the database volume
docker compose logs -f api        # follow one service
docker compose restart api        # after changing .env
docker compose ps                 # health at a glance
```

Both apps hot-reload from bind mounts, so editing `apps/api` or `apps/web` on
the host takes effect without a rebuild. Rebuild only when dependencies change:

```bash
docker compose build api && docker compose up -d api
```

Common tasks:

```bash
docker compose exec api alembic upgrade head
docker compose exec api alembic downgrade -1
docker compose exec api alembic revision --autogenerate -m "add face profiles"
docker compose exec api alembic check          # schema matches the models?
docker compose exec api pytest -q
docker compose exec api python -m app.cli check-config
docker compose exec postgres psql -U postgres -d fvas
```

`make help` lists the same tasks with shorter names.

## 6. What runs where

```
        host                            fvas_default network
  ┌─────────────┐
  │   browser   │──── :3000 ────▶ ┌──────────┐
  └─────────────┘                 │   web    │
         │                        │ Next.js  │
         └──────── :8000 ───────▶ └────┬─────┘
                        ▲              │ API_INTERNAL_URL
                        │              │ http://api:8000
                        │              ▼
                        └───────── ┌──────────┐
                                   │   api    │
                                   │ FastAPI  │
                                   └────┬─────┘
                                        │
                            ┌───────────┴───────────┐
                            ▼                       ▼
                     ┌────────────┐          ┌────────────┐
                     │  postgres  │          │   redis    │
                     │ + pgvector │          │            │
                     └────────────┘          └────────────┘
```

The web container reaches the API **two different ways**, and both are needed:

| Variable | Used by | Value |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | The browser | `http://localhost:8000` |
| `API_INTERNAL_URL` | The Next.js BFF, server-side | `http://api:8000` |

Inside the web container `localhost` is the web container itself, so the BFF
must use the service name. Getting this wrong makes every page load fine while
sign-in fails with `upstream_unavailable` — Compose sets both for you.

## 7. Port conflicts

**The single most likely problem, and the symptom points somewhere else.**

A locally installed PostgreSQL almost always owns port 5432. When that happens
Docker still reports the mapping as bound — it loses the race quietly — so
`docker compose ps` looks healthy and the failure surfaces later as:

```
asyncpg.exceptions.InvalidPasswordError: password authentication failed for user "postgres"
```

That error is real: you reached a *different* PostgreSQL, which has a different
password. Nothing is wrong with the project.

Find out what owns the port:

```powershell
Get-NetTCPConnection -LocalPort 5432 -State Listen |
  ForEach-Object { (Get-Process -Id $_.OwningProcess).ProcessName }
```

```bash
lsof -i :5432          # macOS / Linux
```

Then move the **host** port in `.env` — never `DATABASE_URL`, which is the
address *inside* the network and does not change:

```bash
POSTGRES_PORT=15432
REDIS_PORT=6379
API_PORT=8000
WEB_PORT=3000
```

```bash
docker compose down && docker compose up -d
```

Connect from the host on the new port; containers still talk on 5432 among
themselves:

```bash
psql -h localhost -p 15432 -U postgres -d fvas
```

<a id="troubleshooting"></a>
## 8. Troubleshooting

**`failed to connect to the docker API … the system cannot find the file specified`**
Docker Desktop is not running. The CLI is installed independently of the daemon.

**`Bind for 0.0.0.0:3000 failed: port is already allocated`**
Something else holds the port — often a `npm run dev` you started earlier. Stop
it, or set `WEB_PORT` in `.env`.

**`npm ci` fails during the web build with `npm error stderr: undefined`**
A transient registry failure; no package is named because none was reached.
Re-run `docker compose build web`. If it fails twice, check your network.

**API restarts in a loop**
Read the reason rather than guessing:

```bash
docker compose logs api | tail -30
```

Configuration is validated at startup and the process exits on anything invalid,
so a bad `.env` value shows as an immediate, explicit error rather than broken
requests later.

**`relation "users" does not exist`**
Migrations have not been applied:

```bash
docker compose exec api alembic upgrade head
```

**Console shows "Loading your session…" forever**
The browser cannot reach the API. Confirm `curl http://localhost:8000/health`
works from the host, and that `NEXT_PUBLIC_API_URL` matches the port you
actually published. That value is baked into the client bundle at build time —
after changing it, rebuild:

```bash
docker compose build web && docker compose up -d web
```

**`ModuleNotFoundError` for a package you just added to `pyproject.toml`**

Rebuilding the image is not enough. The API service keeps its virtualenv in an
*anonymous volume* (`- /app/.venv` in the Compose file) so the host bind mount
cannot shadow it — and Docker reuses that volume when the container is
recreated. The new image's `.venv` is mounted over by the old one, and the
package you installed is invisible.

Whenever a Python dependency changes:

```bash
docker compose up -d --build --force-recreate --renew-anon-volumes api
```

`--renew-anon-volumes` is the flag that matters. Without it the symptom is a
missing module that is demonstrably present in the image you just built.

**Editing files does nothing**
Bind mounts on Windows sometimes miss filesystem events. `WATCHPACK_POLLING` is
already set for the web container; for the API, restart it:

```bash
docker compose restart api
```

**Start completely over**

```bash
docker compose down -v
docker compose up -d
docker compose exec api alembic upgrade head
docker compose exec api python -m app.cli seed
```

`-v` destroys the database volume. That is the point, and there is no undo.

## 9. Running against Postgres without Docker

Only the databases need containers; the apps can run natively, which gives
faster reloads and a normal debugger:

```bash
docker compose up -d postgres redis
```

```bash
cd apps/api
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:15432/fvas"
uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload
```

```bash
npm install && npm run dev
```

Leave `API_INTERNAL_URL` unset in this mode — the BFF then falls back to the
public URL, which is correct when everything is on the host.

## 10. Running the test suite against Postgres

The suite defaults to in-memory SQLite so it needs no services and finishes in
seconds. Point it at Postgres to exercise what SQLite cannot model — JSONB,
`citext`, native partial indexes, and server-side defaults:

```bash
docker compose exec postgres psql -U postgres -c "CREATE DATABASE fvas_test;"
```

```bash
cd apps/api
TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:15432/fvas_test" uv run pytest -q
```

It is the same suite either way, so no test is accidentally exempt from the
fidelity run. Expect it to take minutes rather than seconds — each test drops
and recreates the schema.

CI runs both, plus `alembic check`, which fails the build if the migrations and
the models have drifted apart.

## 11. Switching on the real face engine

The stack ships with `FACE_ENGINE=fake`. It is deterministic, needs no model
download, and makes a clean clone work on the first `docker compose up` — which
is why it is the default rather than the real pipeline.

`fake` accepts every face. It is a test double, and the application **refuses to
start** with it set in a production environment.

To run the real pipeline (SCRFD-10GF + ArcFace R50 on ONNX Runtime):

1. Set `FACE_ENGINE=insightface` in `.env`.
2. Rebuild the API image with the optional extra, so `insightface`,
   `onnxruntime` and `opencv-python-headless` are installed:

```bash
docker compose build --build-arg INSTALL_FACE_EXTRA=1 api
```

3. Recreate the container so the new virtualenv is actually used — see the
   anonymous-volume note in §8:

```bash
docker compose up -d --force-recreate --renew-anon-volumes api
```

The first start downloads roughly 350 MB of weights into the named `models`
volume, so it survives `docker compose down`. Startup blocks until they load;
that is deliberate, because a lazy first-request load would hand the first user
of every deploy a multi-second verification.

Raise Docker's memory allocation to 8 GB first: ONNX Runtime holds the weights
resident per worker.

Two settings are already tuned from the Phase 0 measurements and should not be
"optimised" without re-measuring — see
[14 — Phase 0 Spike](14-phase-0-spike.md):

* `ONNX_INTRA_OP_THREADS=2`. Never `0`. ONNX Runtime reads 0 as "every visible
  core", and a container sees the *host's* core count regardless of its CPU
  quota. That oversubscription measured **five times slower** (p95 1674 ms vs
  331 ms). Scale with workers, not threads.
* `FACE_DET_SIZE=320`, not 640. Detection at 640 costs ~2.5× more for recall the
  112 px inter-ocular gate discards anyway.

---

**Previous:** [12 — Repository Standards](12-repository-standards.md)
