# 09 — Security & Compliance

Threat model, controls, the RBAC matrix, and the biometric-data posture.

---

## 1. Threat model

Assets, ranked by what a compromise actually costs:

| # | Asset | Impact if compromised |
| --- | --- | --- |
| 1 | **Face templates** | Irrevocable. A person cannot change their face. This is the only asset where the harm is permanent |
| 2 | **API keys** | Attacker verifies or enrolls as the tenant; can authorize fraudulent actions in the customer's system |
| 3 | **Console credentials** | Full tenant control: keys, members, thresholds, deletion |
| 4 | **Verification logs** | Behavioural profile of the customer's end-users; who was where, when |
| 5 | **Tenant isolation** | One breach becomes every customer's breach |
| 6 | **Availability** | An auth provider that is down blocks the customer's logins |

### Attack surface

| Vector | Control |
| --- | --- |
| Credential stuffing on the console | Argon2id, progressive lockout, per-IP rate limit, breach-list check at registration |
| API key leakage (git, client bundle) | `test`/`live` separation, scopes, IP allowlist, rotation with 24 h overlap, last-used tracking, secret-scanning in CI |
| Cross-tenant access | Repository-level scoping, generated isolation tests, Postgres RLS (Phase 8) |
| **Presentation attack (photo/replay/deepfake)** | Quality gates + optional active challenge; **not certified PAD** — see [08](08-ai-workflow.md#5-liveness--stated-limits) |
| Enumeration of subjects or users | ULIDs, uniform 404s across tenants, no existence disclosure on password reset |
| Injection | SQLAlchemy parameterized queries only; Pydantic validation on every input |
| XSS in the console | React escaping, strict CSP, no `dangerouslySetInnerHTML` outside sanitized MDX, access token never in `localStorage` |
| CSRF | Bearer auth on the API (immune); the BFF's cookie routes use `SameSite=Lax` + origin check |
| SSRF via webhook URLs | Deny private/link-local/loopback ranges, DNS re-resolution check before connect, no redirect following |
| Image-decode exploits | Size cap, format allowlist, dimension cap, decode in a bounded worker |
| Replay of API requests | Idempotency keys; signed webhooks with a 5-minute timestamp window |
| Denial of service | Per-key token bucket, payload caps, request timeout, connection limits |

## 2. Authentication controls

### Passwords

**Argon2id**, `time_cost=3`, `memory_cost=64 MiB`, `parallelism=4`. Memory-hard, so GPU cracking is expensive — the property bcrypt lacks. Minimum 12 characters, checked against a common-password list (offline k-anonymity check, no plaintext leaves the server). No composition rules and no forced rotation: both are documented to push users toward weaker, predictable passwords.

### Tokens

| Token | Lifetime | Storage | Notes |
| --- | --- | --- | --- |
| Access (JWT, HS256) | 15 min | Browser memory | Claims: `sub`, `org_id`, `role`, `jti`, `exp`. Never in `localStorage` |
| Refresh (opaque) | 30 days | httpOnly, Secure, SameSite=Lax cookie | Hashed at rest; rotated on every use |
| Email verification | 24 h | — | Single-use |
| Password reset | 30 min | — | Single-use, invalidates all sessions on use |
| Invitation | 7 days | — | Single-use, email-bound |

**HS256 over RS256** at MVP: one service verifies the tokens it issues, so asymmetric keys add key distribution and rotation complexity for no benefit. The moment a second service needs to verify independently, this becomes RS256 — noted as a known migration.

**Refresh rotation with reuse detection.** Every refresh issues a new token in the same `family_id` and revokes the previous one. Presenting an already-used token means the token was stolen (either the attacker or the legitimate user is replaying), so the **entire family is revoked** and a `token_reuse_detected` event is written to `auth_logs`. This converts an undetectable persistent compromise into a loud, logged event.

### API keys

Format `fvas_{env}_{32 url-safe chars}` — ~190 bits of entropy from `secrets.token_urlsafe`. Verification: parse the prefix → indexed lookup → `hmac.compare_digest` against the stored SHA-256. Constant-time comparison prevents the timing oracle that a naive `==` would create.

Controls: scopes (`enrollment:write`, `verification:write`, `subject:read`, `subject:delete`), optional expiry, optional CIDR allowlist for live keys, revocation effective immediately (no cached auth decisions), and `last_used_at` tracking so a customer can spot a key that should have been retired.

Rationale for SHA-256 rather than a slow hash is in [architecture §6](05-architecture.md#6-authentication-architecture) — it comes down to input entropy and hot-path latency, not convenience.

## 3. Authorization — RBAC

Four system roles. Permissions are `resource:action` strings resolved from an in-code matrix (see [database §4.1](06-database.md#41-identity--tenancy) for why the tables still exist).

| Permission | Owner | Admin | Developer | Viewer |
| --- | :-: | :-: | :-: | :-: |
| `organization:read` | ✓ | ✓ | ✓ | ✓ |
| `organization:update` | ✓ | ✓ | — | — |
| `organization:delete` | ✓ | — | — | — |
| `member:read` | ✓ | ✓ | ✓ | ✓ |
| `member:invite` | ✓ | ✓ | — | — |
| `member:update_role` | ✓ | ✓ ¹ | — | — |
| `member:remove` | ✓ | ✓ ¹ | — | — |
| `apikey:read` | ✓ | ✓ | ✓ | — |
| `apikey:create` | ✓ | ✓ | ✓ | — |
| `apikey:revoke` | ✓ | ✓ | ✓ | — |
| `subject:read` | ✓ | ✓ | ✓ | ✓ |
| `subject:write` | ✓ | ✓ | ✓ | — |
| `subject:delete` | ✓ | ✓ | — | — |
| `enrollment:write` | ✓ | ✓ | ✓ | — |
| `verification:write` | ✓ | ✓ | ✓ | — |
| `verification:read` | ✓ | ✓ | ✓ | ✓ |
| `settings:read` | ✓ | ✓ | ✓ | ✓ |
| `settings:update` | ✓ | ✓ | — | — |
| `threshold:update` | ✓ | — | — | — |
| `webhook:manage` | ✓ | ✓ | ✓ | — |
| `audit:read` | ✓ | ✓ | — | ✓ ² |
| `billing:manage` | ✓ | — | — | — |

¹ An Admin cannot modify or remove an Owner.
² Viewer gets audit read specifically so a compliance officer can be given a genuinely read-only account. That is a real persona, and forcing them into an Admin seat to read logs would be a security failure caused by a permissions model that was too coarse.

**Enforced invariants:** at least one active Owner per organization at all times; role changes and member removals are always audit-logged with actor and target; the frontend disables unpermitted controls and the backend independently enforces — the client check is UX, the server check is security.

## 4. Biometric data protection

The controls that specifically follow from "this data is irrevocable":

| Control | Implementation |
| --- | --- |
| **Minimization** | Only the embedding is stored. Raw images are discarded after processing unless the organization explicitly enables retention, which is off by default and surfaced in settings with a plain-language warning |
| **Purpose limitation** | Templates are used only for verification and same-tenant duplicate detection. No training, no sharing, no analytics on the vectors themselves |
| **Encryption in transit** | TLS 1.3 minimum, HSTS with preload |
| **Encryption at rest** | Full-disk/volume encryption (AES-256) on the database host; automated backups encrypted with a separate key |
| **Access control** | The application connects with a least-privilege role. No human has standing production database access; break-glass access is time-boxed, approved, and logged |
| **Deletion** | `DELETE /v1/subjects/{id}` physically removes template rows, propagates to backups within the 30-day backup rotation, and writes an audit entry. The subject row is soft-deleted for audit continuity; **the biometric data is not** |
| **Export** | `POST /v1/console/logs/export` and a per-subject data export satisfy access requests |
| **Consent** | `consent_reference` on the subject records the customer's proof. Fvas is the processor; the customer is the controller and holds the lawful basis |

### The application-layer encryption trade-off — stated openly

Column-level encryption of the `embedding` column would protect against a database-only compromise (a leaked backup, a read replica misconfiguration). It is **not implemented at MVP**, for one concrete reason: an encrypted column cannot be indexed by pgvector, which removes duplicate detection entirely and makes any future 1:N feature impossible.

The position taken: disk-level encryption + least-privilege access + no standing human access covers the realistic threat (stolen media, leaked backup) at acceptable cost, while column encryption would break a shipped feature to defend against an attacker who, in most scenarios that get them the ciphertext, would also get the key.

The roadmap answer is envelope encryption with a KMS-managed key and a separate searchable index — real work, scheduled honestly, not claimed now. Pretending an unimplemented control exists is worse than not having it.

## 5. Transport & application hardening

**Security headers**, set by middleware on every response:

```
Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(self), microphone=(), geolocation=()
Content-Security-Policy: default-src 'self'; img-src 'self' data: blob:;
  script-src 'self'; style-src 'self' 'unsafe-inline';
  connect-src 'self' https://api.fvas.io; frame-ancestors 'none'
```

`Permissions-Policy` explicitly grants `camera=(self)` — the product needs it — and explicitly denies microphone and geolocation, which it never needs. Being specific about what a biometric product does *not* access is a meaningful trust signal.

**CORS** — explicit origin allowlist, never `*`. Credentials allowed only on the console origin. The public API is called server-to-server and does not need CORS credentials at all.

**Input validation** — Pydantic v2 on every request body, query, and path parameter. Images: format allowlist, ≤ 8 MB, ≤ 4096×4096, magic-byte check (never trust the declared content type), decode inside a bounded worker with a timeout. `metadata` JSON capped at 8 KB and depth-limited.

**Rate limiting** — Redis token bucket keyed by API key, then by IP as a fallback. Auth endpoints are limited per IP *and* per account, so an attacker cannot lock out a specific user by burning the shared IP budget.

**Secrets** — never in the repo. `.env.example` carries names only. Environment variables in dev, the platform secret store in production. `gitleaks` runs in CI and blocks the merge on a hit.

## 6. Audit logging

Every mutating action produces an `audit_logs` row: actor (user or key), action, resource type and ID, before/after with sensitive fields redacted, IP, user agent, request ID, timestamp.

Design constraints that make the log trustworthy:

- **Append-only.** The application's database role has no `UPDATE` or `DELETE` grant on `audit_logs`. An audit log the application can rewrite proves nothing
- **Written in the same transaction** as the change it records, so a committed change without its audit entry is not representable
- **Never contains secrets** — key values, tokens, password hashes, or embeddings. A redaction test asserts this against the sensitive-field list
- **Exportable** as CSV/JSON, because a compliance officer's job is producing evidence to someone else

## 7. Regulatory position

| Regime | Relevance | Position |
| --- | --- | --- |
| **UU PDP No. 27/2022 (Indonesia)** | Biometric data is specific personal data requiring explicit consent | Primary regulatory context. Consent captured by the controller and referenced by API; data residency in `ap-southeast`; breach-notification process documented |
| **GDPR Art. 9** | Biometric data for unique identification is a special category | Fvas is the processor; the customer is the controller. DPA available; Art. 15/17 supported by export and hard-delete endpoints |
| **SOC 2 Type II** | Enterprise procurement requirement | Not certified. Controls are being built to be auditable — audit logging, access control, change management via PRs. Stated as a roadmap item, never implied as present |
| **ISO/IEC 30107-3 (PAD)** | The standard for presentation-attack detection | Not certified, and stated as such wherever liveness is mentioned |

Claiming a certification that does not exist is the fastest way to lose an enterprise deal and the only compliance mistake that is unrecoverable. Everything above is written to be true today.

## 8. Incident response

| Phase | Action |
| --- | --- |
| Detect | Alerts on auth-failure spikes, `token_reuse_detected`, 5xx rate, quota anomalies, webhook failure storms |
| Contain | Revoke the affected keys or token families; disable the account; rotate the platform secret |
| Assess | Reconstruct from `audit_logs` + `auth_logs` + request logs, joined on `request_id` |
| Notify | Affected controllers within 72 h (GDPR) / per UU PDP timelines; template exposure is treated as maximum severity by default |
| Remediate | Fix, add a regression test, publish a post-mortem |

The `request_id` threading through the response header, the application logs, and the audit log is what makes the assess phase take minutes instead of days. It costs one middleware.

## 9. Security checklist for release

- [ ] No secrets in the repo; `gitleaks` clean
- [ ] All dependencies scanned (`pip-audit`, `npm audit`), no unresolved high/critical
- [ ] Tenant isolation tests pass for every list and get endpoint
- [ ] RBAC matrix tested per role per endpoint
- [ ] Rate limits verified under load
- [ ] Security headers present on every response (asserted in tests, not eyeballed)
- [ ] CSP has no `unsafe-eval`
- [ ] Log-redaction test passes for tokens, keys, embeddings, and image bytes
- [ ] Password reset does not disclose account existence
- [ ] Cross-tenant requests return 404, never 403 (403 confirms existence)
- [ ] Webhook URLs rejected for private ranges
- [ ] Deletion verified: templates physically gone, audit entry present

---

**Next:** [10 — Development Roadmap](10-roadmap.md)
