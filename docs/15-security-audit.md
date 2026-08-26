# 15 — Security audit (Phase 8)

Run 2026-08-01 against the state of `main` at the end of Phase 8. Every finding
below is either fixed or accepted with a reason; nothing is listed without a
disposition.

---

## 1. Dependency audit

### Python — `pip-audit --strict --desc`

```
No known vulnerabilities found
```

### JavaScript — `npm audit --audit-level=high`

**Before:** 1 critical, 4 high.
**After:** 0 critical, 4 high — all in one dependency tree, all accepted below.

| Package | Severity | Direct? | Disposition |
| --- | --- | :-: | --- |
| `vitest` / `@vitest/mocker` | **critical** | yes | **Fixed.** Upgraded 2.1 → 3.x. Suite re-run: 35/35 pass. |
| `next` | high | yes | Accepted — see below |
| `postcss` | high | no | Accepted — transitive via `next` |
| `sharp` (libvips) | high | no | Accepted — transitive via `next` |
| `vite` | high | no | Accepted — transitive via `next` |

**Why the four highs are accepted rather than fixed.**

All four resolve only by upgrading Next 15 → 16, a major version bump. Doing
that as an unreviewed side effect of an audit run — across 46 routes, at the end
of a build phase — would trade a set of non-exploitable findings for a real risk
of breaking the product. `npm audit fix --force` proposes `next@9.3.3`, a
six-major *downgrade*, which is worse than either option.

Exposure was assessed individually rather than waved away:

| Finding | Reachable here? |
| --- | --- |
| `postcss` — XSS via unescaped `</style>` in CSS stringify | **No.** Runs at build time over CSS we author. There is no path for attacker-controlled input to reach the stringifier. |
| `sharp` / libvips CVEs | **No.** `sharp` backs `next/image` optimization. The app configures no `remotePatterns` and renders no remote images — the only `<img>` in the console is a local `data:` URL from the operator's own camera, which bypasses the optimizer entirely. |
| `vite` — path traversal in optimized-deps `.map` handling | **No.** Vite is present only as a `vitest` dependency. It never runs in production, and the dev server is not exposed. |

**Action:** Next 16 upgrade tracked as its own change, to be done with its own
verification pass rather than folded into a dependency bump.

### Secret scanning — `gitleaks`

Wired in CI over full history (`fetch-depth: 0`), not just the diff. No findings.

---

## 2. Tenancy

Four independent layers, listed weakest-first so the ordering is honest about
what each actually buys:

| Layer | What it catches | Verified by |
| --- | --- | --- |
| Composite indexes leading with `organization_id` | Nothing on its own — a performance property | — |
| `TenantScopedRepository._scoped()` | A query author forgetting the filter | Every repository read goes through it |
| Generated cross-tenant tests | An endpoint added without isolation | 30 route/method pairs, **zero skips**, both auth planes |
| **PostgreSQL RLS** | A raw query that bypasses all of the above | `tests/test_row_level_security.py` |

### The RLS finding

Migration 0008 enabled and forced row-level security. **It protected nothing.**

The stack connects as `postgres`, a superuser, and superusers bypass RLS
unconditionally — `FORCE ROW LEVEL SECURITY` binds only the table *owner*.
Verified directly: with policies live, tenant B could read tenant A's subjects
and successfully insert a row owned by A.

Migration 0009 adds a `fvas_app` role that is `NOSUPERUSER NOBYPASSRLS`, with
DML grants and no DDL. Re-run as that role:

| Check | Result |
| --- | --- |
| Unfiltered `SELECT` as tenant B | Only B's rows |
| Unfiltered `SELECT` with **no tenant bound** | **0 rows** — fails closed |
| Tenant B inserting a row owned by A | `ERROR: new row violates row-level security policy` |
| Application deleting from `audit_logs` | `ERROR: permission denied` |

`current_setting('fvas.organization_id', true)` returns NULL when unset, and
NULL never equals a text column — so a forgotten `set_tenant` exposes nothing
rather than everything. Failing open there would have been worse than no policy,
because it would have looked like protection.

**Known limitation, stated rather than buried:** development and the default
`docker-compose` still connect as `postgres`, so **RLS is inert in
development**. Production must set `DATABASE_URL` to the `fvas_app` role. The
identity bootstrap tables (`users`, `memberships`, `roles`, `api_keys`,
`organizations`) deliberately carry no policy — they are read to determine which
tenant the caller belongs to, before any tenant is known.

---

## 3. Credentials

| Control | State |
| --- | --- |
| Password hashing | Argon2id, 64 MiB memory cost |
| API key hashing | SHA-256, justified by 190 bits of input entropy and hot-path latency |
| Key comparison | `hmac.compare_digest` — constant time |
| Unknown-prefix rejection | Hashes a decoy so a nonexistent key is not measurably faster to reject |
| Key reveal | Once, at creation. Only a digest is stored |
| Revocation | Checked per request, never cached — `200` then `401` on the next call, measured |
| Rotation | 24 h overlap so a deploy has no 401 window |
| Refresh tokens | Rotating, with family reuse detection |
| Audit log | No `UPDATE`/`DELETE` grant for the application role |

### The key-generation bug

`secrets.token_urlsafe` draws from the URL-safe base64 alphabet, which includes
`_`. The prefix parser split on `_` without a `maxsplit`, so **roughly 45% of
generated keys failed to authenticate** — measured at 90/200. Found by minting a
key through the API and immediately failing to use it. Fixed with `maxsplit=2`
and a 300-iteration regression test.

---

## 4. Transport and headers

CORS exposes `X-RateLimit-*`, `Retry-After`, `X-Request-ID` and
`Idempotent-Replay`. That gap was real: the docs promised rate-limit headers on
every response, and before the fix a browser client could see a `429` but not
how long to wait — the documented contract held only for server-side callers.

---

## 5. What this audit did **not** cover

Listed because an audit that only reports what it looked at is misleading:

- **No penetration test.** No attempt was made to break the running system from
  outside.
- **No dependency review of transitive Python packages beyond `pip-audit`'s
  advisory database.**
- **No threat model for the face pipeline itself** — adversarial inputs designed
  to crash or mislead the detector were not tested.
- **Presentation-attack detection remains heuristic**, and its limits are stated
  in [08 — AI workflow §5](08-ai-workflow.md) rather than treated as solved.
- **Container image scanning** (`trivy` or equivalent) is not in CI.
