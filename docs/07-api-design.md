# 07 — REST API Design

Two surfaces, one codebase. Conventions first, then the resource reference.

---

## 1. Two API surfaces

| | **Public API** | **Console API** |
| --- | --- | --- |
| Base path | `/v1` | `/v1/console` |
| Consumer | The customer's servers and apps | The Fvas dashboard |
| Auth | `Authorization: Bearer fvas_live_…` | `Authorization: Bearer <JWT>` |
| Stability | Versioned, deprecation policy applies | Internal; may change with the frontend |
| Docs | Public, in the docs site and Swagger | Swagger only |
| Rate limit | Per API key | Per user |

Separating them is what allows the console to iterate freely without breaking a customer's production integration. It also means a stolen API key can never reach organization settings, member management, or billing — a boundary that a single `/v1` surface with scope flags would leave one bug away from failing.

## 2. Conventions

**Versioning** — URI path (`/v1`). Header and content-negotiation versioning are more elegant and less usable: a URL that can be pasted into a browser, a curl example, or a support ticket is worth more than elegance here. Breaking changes get `/v2`, with a minimum 12-month overlap and `Sunset` headers on the old surface.

**Naming** — plural nouns, no verbs. Actions that aren't CRUD become subresources (`POST /v1/api-keys/{id}/rotate`) rather than RPC endpoints.

**Methods** — `GET` read · `POST` create/action · `PATCH` partial update · `DELETE` remove. `PUT` is not used; partial update is the realistic case and having one update verb removes ambiguity.

**Request/response** — JSON only, `snake_case` keys (matching Python and SQL; the TypeScript client maps at the boundary). Images are base64 in JSON *or* `multipart/form-data`, both accepted. Base64 costs ~33% more bytes but is dramatically easier to use from a server-side integration, which is the primary path.

**Timestamps** — RFC 3339 UTC with a `Z` suffix, always.

**Pagination** — cursor-based:

```http
GET /v1/subjects?limit=20&cursor=eyJpZCI6InN1Yl8wMUhR...
```
```json
{
  "data": [ … ],
  "pagination": { "next_cursor": "eyJpZCI6…", "has_more": true, "limit": 20 }
}
```

Offset pagination on `verification_sessions` would skip and duplicate rows, because rows are inserted continuously while a user pages. The cursor is an opaque base64 of `(created_at, id)`. Cost: no jump-to-page-7. Acceptable — nobody navigates a log by page number, they filter.

**Filtering** — explicit query parameters, no generic query language: `?decision=rejected&subject_id=sub_…&from=2026-07-01T00:00:00Z&to=2026-07-30T23:59:59Z`. A generic filter DSL is a security and performance liability (unbounded queries against a shared database) for a benefit no MVP customer has asked for.

**Idempotency** — `POST /v1/verifications` and `POST /v1/enrollments` accept `Idempotency-Key`. The first response is cached in Redis for 24 h and replayed for repeats. A retried network call must not double-charge a customer's quota or create a second profile.

**Errors** — one envelope, always:

```json
{
  "error": {
    "code": "below_threshold",
    "message": "Similarity 0.291 is below the configured threshold of 0.380.",
    "details": { "similarity": 0.291, "threshold": 0.38 },
    "request_id": "req_01HQZX8K4M2N"
  }
}
```

| Status | When |
| --- | --- |
| `400 invalid_request` | Malformed body, bad image encoding |
| `401 unauthenticated` | Missing, malformed, revoked, or expired credential |
| `403 forbidden` | Valid credential, insufficient scope or role |
| `404 not_found` | Missing — **or existing in another tenant** (never distinguish; that would leak existence) |
| `409 conflict` | `external_id` already exists, duplicate face detected |
| `413 payload_too_large` | Image over 8 MB |
| `422 unprocessable_entity` | Schema-valid but semantically invalid |
| `429 rate_limited` | Includes `Retry-After` |
| `500 internal_error` | Never leaks internals; carries `request_id` |
| `503 service_unavailable` | Face engine unavailable / degraded |

Note that a failed *verification* is a `200`, not a `4xx`. "This is not the right person" is a successful answer to the question asked. Only a failed *request* is an error. Conflating the two forces every integrator to write awkward error handling around normal business outcomes.

**Rate limits** — token bucket in Redis, per key. Headers on every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.

| Endpoint class | Free | Startup | Growth |
| --- | --- | --- | --- |
| `POST /v1/verifications` | 10/s | 50/s | 200/s |
| `POST /v1/enrollments` | 2/s | 10/s | 50/s |
| Reads | 20/s | 100/s | 300/s |
| Console auth | 5/min per IP | | |

## 3. Public API reference

### 3.1 Subjects

| Method | Path | Scope | Description |
| --- | --- | --- | --- |
| `POST` | `/v1/subjects` | `subject:write` | Create a subject |
| `GET` | `/v1/subjects` | `subject:read` | List, filterable by `status`, `external_id` |
| `GET` | `/v1/subjects/{id}` | `subject:read` | Retrieve (accepts `ext_<external_id>` as an alias) |
| `PATCH` | `/v1/subjects/{id}` | `subject:write` | Update name, metadata, status |
| `DELETE` | `/v1/subjects/{id}` | `subject:delete` | Delete subject **and all biometric templates**, permanently |

```http
POST /v1/subjects
{
  "external_id": "user_84213",
  "display_name": "Rani Wulandari",
  "consent_reference": "consent_2026_07_30_84213",
  "metadata": { "tier": "premium", "branch": "jkt-01" }
}
```
```json
{
  "id": "sub_01HQZX8K4M2N7P",
  "external_id": "user_84213",
  "status": "pending",
  "verification_count": 0,
  "created_at": "2026-07-30T07:22:08Z"
}
```

Status is `pending` until a face is enrolled. `consent_reference` is required when the organization has consent enforcement on — Fvas is the processor, and the contract makes the controller's obligation explicit rather than implicit.

### 3.2 Enrollments

| Method | Path | Scope | Description |
| --- | --- | --- | --- |
| `POST` | `/v1/enrollments` | `enrollment:write` | Enroll a face; creates or supersedes a profile |
| `GET` | `/v1/enrollments` | `subject:read` | List attempts, including failures |
| `GET` | `/v1/enrollments/{id}` | `subject:read` | Attempt detail with the quality report |
| `DELETE` | `/v1/subjects/{id}/face-profile` | `subject:delete` | Revoke the active profile, keeping the subject |

Reading and deleting enrollments reuse the *subject* permissions rather than
introducing `enrollment:read` and `enrollment:delete`. An enrollment attempt is
a fact about a subject, and anyone who can read the subject can already see
whether they are enrolled; a separate permission would be one more thing to get
wrong in the matrix without protecting anything new. The
[RBAC matrix](09-security.md#3-authorization--rbac) is the authority — if these
two documents disagree, that one is right.

```http
POST /v1/enrollments
Idempotency-Key: idem_7c1f...
{
  "subject_id": "sub_01HQZX8K4M2N7P",
  "images": ["<base64>", "<base64>", "<base64>"],
  "options": { "check_duplicates": true, "min_quality": 0.6 }
}
```
```json
{
  "id": "enr_01HQZX9M2P4Q",
  "status": "succeeded",
  "face_profile": {
    "id": "fp_01HQZX9M2P4R", "version": 1,
    "template_count": 3, "avg_quality_score": 0.842,
    "model": { "name": "buffalo_l", "version": "w600k_r50" }
  },
  "images": [
    { "index": 0, "accepted": true, "quality_score": 0.871, "checks": { … } },
    { "index": 1, "accepted": true, "quality_score": 0.834, "checks": { … } },
    { "index": 2, "accepted": true, "quality_score": 0.821, "checks": { … } }
  ],
  "latency_ms": 612
}
```

Per-image results are returned even on success, because an integrator building a capture UI needs to know *which* frame was weak in order to coach their user.

**Duplicate detected → `409`:**

```json
{ "error": {
    "code": "duplicate_face_detected",
    "message": "This face closely matches an existing enrolled subject.",
    "details": { "matched_subject_id": "sub_01HQ…", "similarity": 0.734,
                 "threshold": 0.6, "override_with": "check_duplicates=false" },
    "request_id": "req_…" } }
```

The error tells the caller exactly how to proceed deliberately. An error that describes a problem without describing the resolution is half an error.

### 3.3 Verifications — the core endpoint

| Method | Path | Scope | Description |
| --- | --- | --- | --- |
| `POST` | `/v1/verifications` | `verification:write` | Verify a face against a subject |
| `GET` | `/v1/verifications` | `verification:read` | List sessions |
| `GET` | `/v1/verifications/{id}` | `verification:read` | Session detail |

```http
POST /v1/verifications
Authorization: Bearer fvas_live_9f2c…
Idempotency-Key: idem_a91e…
{
  "subject_id": "sub_01HQZX8K4M2N7P",
  "image": "<base64 jpeg>",
  "options": { "threshold": 0.42, "require_liveness": false }
}
```

```json
{
  "id": "vs_01HQZXA4B6C8",
  "decision": "verified",
  "subject_id": "sub_01HQZX8K4M2N7P",
  "similarity": 0.8121,
  "threshold": 0.42,
  "confidence": "high",
  "quality": { "sharpness": 0.86, "brightness": 0.71, "face_size_px": 214,
               "pose": { "yaw": -4.2, "pitch": 1.8, "roll": 0.4 } },
  "templates_compared": 3,
  "timing": { "total_ms": 284, "detect_ms": 62, "embed_ms": 148, "match_ms": 31 },
  "created_at": "2026-07-30T07:24:11Z"
}
```

| Decision | Meaning |
| --- | --- |
| `verified` | Similarity ≥ threshold |
| `rejected` | Similarity < threshold — a real face, not this person |
| `inconclusive` | Could not decide: no face, multiple faces, quality gate failed, liveness failed |
| `error` | Pipeline failure — not the caller's fault, do not count against quota |

The three-way outcome matters. Collapsing `inconclusive` into `rejected` would tell a customer's user "you are not who you say you are" when the truth is "the room is too dark" — and it would corrupt the customer's fraud metrics with lighting problems.

`options.threshold` may only be **stricter** than the organization default. Allowing a per-request loosening would let a compromised key silently weaken the security posture the organization configured.

### 3.4 Webhooks

Events: `verification.completed`, `verification.failed`, `enrollment.completed`, `enrollment.duplicate_detected`, `subject.deleted`, `quota.threshold_reached`.

```http
POST https://customer.example.com/webhooks/fvas
Fvas-Signature: t=1753859051,v1=5257a869e7ec…
Fvas-Event-Id: evt_01HQZXB…
```

Signed HMAC-SHA256 over `{timestamp}.{raw_body}`. The timestamp is inside the signed payload so a captured request cannot be replayed later; receivers reject anything older than 5 minutes. Retries: 8 attempts with exponential backoff over ~24 h. Delivery is at-least-once — receivers must dedupe on `Fvas-Event-Id`, which is documented prominently rather than hidden in a footnote.

## 4. Console API reference

Same conventions, JWT auth, role-checked. Abbreviated:

| Group | Endpoints |
| --- | --- |
| **Auth** | `POST /auth/register` · `login` · `refresh` · `logout` · `verify-email` · `forgot-password` · `reset-password` · `GET /auth/me` |
| **Organizations** | `POST /organizations` · `GET /organizations` (mine) · `GET|PATCH /organizations/{id}` · `GET|PATCH /organizations/{id}/settings` |
| **Members** | `GET /organizations/{id}/members` · `PATCH /members/{id}` (role) · `DELETE /members/{id}` · `POST /invitations` · `GET /invitations` · `DELETE /invitations/{id}` · `POST /invitations/accept` |
| **API keys** | `GET|POST /api-keys` · `POST /api-keys/{id}/rotate` · `DELETE /api-keys/{id}` |
| **Biometrics** | Console-side proxies of subjects / enrollments / verifications, JWT-scoped |
| **Analytics** | `GET /analytics/overview` · `/timeseries` · `/outcomes` · `/failure-reasons` · `/latency` |
| **Logs** | `GET /logs/audit` · `/logs/auth` · `/logs/requests` · `POST /logs/export` |
| **Webhooks** | `GET|POST /webhooks` · `PATCH|DELETE /webhooks/{id}` · `POST /webhooks/{id}/test` · `GET /webhooks/{id}/deliveries` |
| **Usage** | `GET /usage/current` · `GET /usage/history` |

## 5. OpenAPI & documentation

FastAPI generates OpenAPI 3.1 from the Pydantic models — the schema cannot drift from the implementation, which is the main reason for choosing FastAPI over a framework where the spec is a separate artifact.

| Surface | URL |
| --- | --- |
| Swagger UI | `/docs` |
| ReDoc | `/redoc` |
| Raw schema | `/openapi.json` |

Quality requirements enforced in review: every endpoint has a `summary`, a `description`, a `tags` entry, and at least one `response_model` example; every error code an endpoint can emit is declared in `responses`. An OpenAPI schema without examples is a type listing, not documentation.

The schema is committed to the repo and diffed in CI. A change to a public response model that is not accompanied by a version note fails the build — this is how a versioning policy becomes real instead of aspirational.

## 6. Client experience

**Official client (Phase 7)** — a thin TypeScript SDK generated from OpenAPI plus a hand-written ergonomic layer:

```ts
const fvas = new Fvas(process.env.FVAS_API_KEY!);
const { decision, similarity } = await fvas.verifications.create({
  subjectId: "sub_01HQZX8K4M2N7P",
  image: buffer,
});
```

**Docs code samples** in cURL, Node, Python, and Go on every endpoint. Go is included despite no Go SDK because a copy-pasteable `net/http` example costs 15 lines and removes a real adoption barrier for backend teams.

**Test mode** is a first-class concept, not a sandbox URL: `fvas_test_` keys write to the same schema with an `environment` flag, so test data appears in the console (with a "Test mode" banner) but never counts toward billing or production analytics. A separate sandbox host is a second environment to keep in sync and to explain.

---

**Next:** [08 — AI Workflow](08-ai-workflow.md)
