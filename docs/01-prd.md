# 01 — Product Requirements Document

**Product:** Fvas — Face Authentication Platform
**Stage:** MVP
**Status:** Approved blueprint
**Owner:** Founding team

---

## 1. Problem

Applications increasingly need to prove that a *person* — not just a session, password, or OTP-receiving SIM card — is behind a sensitive action. Approving a loan disbursement, releasing a shipment, unlocking a clinician's access to patient records, confirming a high-value transfer.

Password and OTP factors verify possession, not identity. They are phishable, shareable, and transferable. A team that decides it needs a biometric factor then hits a wall:

| Path | Why teams abandon it |
| --- | --- |
| Build in-house | Requires ML engineering, model selection, threshold calibration, GPU/CPU inference ops, and a biometric-data compliance posture. Months of work outside the team's domain. |
| Hyperscaler face API | Priced and shaped for the platform's own model of tenancy. No organization/member/role concept, no per-customer thresholds, no audit surface a compliance officer can use. Data residency is a negotiation. |
| KYC / onboarding vendor | Optimized for one-time document + selfie onboarding, priced per onboarding. Using it for daily re-authentication is economically absurd. |

The gap: **a developer-first authentication layer, priced per verification, multi-tenant and auditable out of the box.**

## 2. Product statement

> Fvas is a B2B SaaS platform that lets any application add face authentication through an API — enroll a subject once, verify them in under a second, and get a compliance-grade audit trail for free.

**What Fvas is not**, stated explicitly because scope creep here is fatal:

- Not an attendance/HR system
- Not a surveillance or 1:N-at-scale identification product
- Not a full KYC suite (no document OCR, no AML screening, no liveness-as-a-standalone product)
- Not an on-device SDK product at MVP

## 3. Target customers

### Ideal Customer Profile

Digital-first companies, 10–200 engineers, operating in a regulated or fraud-exposed vertical, that already have their own user base and their own login — they need a *step-up* factor, not a whole IdP.

| Segment | Trigger | Job to be done |
| --- | --- | --- |
| **Digital lending / fintech** | Fraudulent disbursement, account takeover | Verify the borrower's face before releasing funds |
| **Healthcare platforms** | Access control to patient data | Confirm the clinician at the terminal is the licensed clinician |
| **Logistics / field ops** | Driver identity fraud, proxy drivers | Verify the driver at handover, on a phone, offline-tolerant |
| **HR-tech / payroll SaaS** | Ghost employees, proxy check-in | Give *their* customers a face factor without building it |
| **Crypto / trading** | Withdrawal fraud | Step-up before a withdrawal above a threshold |

### Personas

| Persona | Role | Success looks like |
| --- | --- | --- |
| **Rani — Backend Engineer** | Integrator, first user of the product | Enrolled a test subject and got a `verified` response within 15 minutes of signup, without talking to sales |
| **Adit — Engineering Manager** | Buyer of the technical decision | Can see error rates, p95 latency, and quota burn without opening a ticket |
| **Sari — Compliance / Risk Officer** | Blocker or enabler of the purchase | Can export an audit log proving who was verified, when, from where, and can prove raw photos are not retained |
| **Bagas — Founder / CTO** | Economic buyer | Predictable per-verification pricing, no lock-in, clear data-residency answer |

Rani is the primary persona. **The product is designed so Rani succeeds alone.** Every UX decision defers to time-to-first-verification.

## 4. Goals & success metrics

### Product goals

| # | Goal | Metric | MVP target |
| --- | --- | --- | --- |
| G1 | Developer reaches value fast | Time to first successful verification (signup → 200 OK) | **< 10 minutes**, self-serve |
| G2 | The system is trustworthy as an auth factor | TAR @ FAR = 1e-4 on the validation set | **≥ 97%** |
| G3 | It is fast enough to sit in a login flow | p95 verification latency (server-side) | **< 800 ms** |
| G4 | It is operable | API availability | **≥ 99.5%** monthly |
| G5 | It is demonstrable | Full enroll → verify → audit demo without a code editor | Achievable from the console alone |

### Anti-goals

- We will **not** optimize for accuracy at the cost of explainability. A rejected verification must always state a reason.
- We will **not** ship features that require retaining raw biometric images by default.
- We will **not** build a second, worse IdP. Fvas is a factor, not a login system.

## 5. Scope

### 5.1 In scope — MVP

**Public website**
Landing, Features, Use Cases, Pricing, Documentation, API Playground, FAQ, Contact, Legal.

**Identity & tenancy**
Email/password registration, email verification, login, forgot/reset password, organization creation, member invitation by email, four roles (Owner, Admin, Developer, Viewer), organization switching.

**Console**
Overview dashboard, Subjects, Enrollments, Verification Sessions, API Keys, Logs (auth + audit), Analytics, Members, Settings, Command palette.

**Face authentication**
Browser camera capture with live quality feedback, guided multi-shot enrollment, verification, duplicate-face detection at enrollment, per-organization threshold presets, re-enrollment and template revocation.

**API**
Public REST API (API-key auth) for subjects, enrollments, verifications; Console API (JWT) for everything the dashboard does; OpenAPI 3.1 + Swagger UI; webhooks for verification and enrollment events; an in-browser API playground running against the caller's own test key.

**Platform**
Rate limiting, quota metering, audit logging, structured logs, health/readiness probes, Docker Compose, CI.

### 5.2 Out of scope — MVP (with rationale)

| Deferred | Why | Revisit |
| --- | --- | --- |
| Active/passive liveness certified to ISO 30107-3 (PAD) | Requires a dedicated model, an attack dataset, and third-party certification. MVP ships **quality gates + an optional active challenge** and documents the residual risk honestly — see [§8](#8-known-risks--honest-limitations). | Phase 10 |
| 1:N identification at scale | Different product, different cost curve. MVP does 1:N only within a tenant, only for duplicate detection at enrollment. | Post-MVP |
| Mobile SDKs (iOS/Android/Flutter) | Web capture proves the flow; native SDKs are a distribution investment, not a validation one. | Post-MVP |
| SSO / SAML / SCIM | Enterprise procurement feature. No design-time risk in deferring. | Enterprise tier |
| On-prem / VPC deployment | High-value for regulated buyers but an entire delivery motion. Architecture keeps it possible (single container + Postgres). | Enterprise tier |
| Billing & payment collection | Stripe integration is well-understood and adds no product learning. MVP **meters and displays** usage against plan limits without charging. | Phase 10 |
| Document OCR / AML | Different product. | Never (partner instead) |

Deferring billing while still building metering is deliberate: metering is the hard, architecturally-entangled half, and it is what makes the dashboard credible in a demo. Charging is a two-week integration whenever it's needed.

## 6. Functional requirements

Priority uses MoSCoW. Every requirement is testable.

### FR-1 Authentication & organizations

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-1.1 | A visitor can register with email + password; password ≥ 12 chars, checked against a common-password list | Must |
| FR-1.2 | Registration creates a personal organization automatically; the user becomes its Owner | Must |
| FR-1.3 | Email must be verified before API keys can be created | Must |
| FR-1.4 | Login returns a short-lived access token (memory) + rotating refresh token (httpOnly cookie) | Must |
| FR-1.5 | A user can request a password reset; the token is single-use and expires in 30 minutes | Must |
| FR-1.6 | An Owner/Admin can invite a member by email with a role; the invite expires in 7 days | Must |
| FR-1.7 | A user can belong to multiple organizations and switch between them without re-login | Must |
| FR-1.8 | The last Owner of an organization cannot be removed or demoted | Must |
| FR-1.9 | Sessions can be revoked from Settings → Sessions | Should |

### FR-2 Subjects & enrollment

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-2.1 | A subject is created with a tenant-supplied `external_id`, unique within the organization | Must |
| FR-2.2 | Enrollment accepts 1–5 images; ≥ 3 recommended and the UI guides toward it | Must |
| FR-2.3 | Each image passes quality gates (single face, min 112 px inter-ocular, blur, brightness, pose) before embedding | Must |
| FR-2.4 | Failed quality checks return a specific machine-readable reason and human-readable guidance | Must |
| FR-2.5 | On enrollment, the system searches existing templates in the tenant for a near-duplicate face and flags it | Should |
| FR-2.6 | Raw images are discarded after embedding unless the organization explicitly opts into retention | Must |
| FR-2.7 | A subject can be re-enrolled; the previous profile is superseded, not deleted, and remains auditable | Should |
| FR-2.8 | Deleting a subject irreversibly deletes its templates within 24 h and records the deletion in the audit log | Must |

### FR-3 Verification

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-3.1 | Verification accepts a `subject_id` + one image and returns `verified` / `rejected` / `inconclusive` | Must |
| FR-3.2 | The response always includes `similarity`, the `threshold` applied, and `latency_ms` | Must |
| FR-3.3 | A rejection always includes a `reason` code | Must |
| FR-3.4 | The threshold is configurable per organization via three presets (Lenient / Balanced / Strict) plus a custom value | Must |
| FR-3.5 | Every attempt is persisted with client IP, user agent, key ID, and outcome — including failures | Must |
| FR-3.6 | An optional active challenge ("blink", "turn left") can be required per organization | Could |
| FR-3.7 | Verification is idempotent on an `Idempotency-Key` header for 24 h | Should |

### FR-4 API & developer experience

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-4.1 | Two independent auth surfaces: API key (public API) and JWT (console API) | Must |
| FR-4.2 | Keys are prefixed `fvas_test_` / `fvas_live_`; test keys never touch live data | Must |
| FR-4.3 | The full secret is shown exactly once, at creation | Must |
| FR-4.4 | Keys are stored as SHA-256 hashes; only prefix + last 4 are recoverable | Must |
| FR-4.5 | OpenAPI 3.1 schema is served and Swagger UI is available | Must |
| FR-4.6 | The docs site includes a playground that executes real requests with the user's test key | Should |
| FR-4.7 | Webhooks are delivered for `verification.completed`, `enrollment.completed`, `enrollment.duplicate_detected`, signed HMAC-SHA256, retried with backoff | Should |

### FR-5 Observability for the customer

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-5.1 | Overview shows verifications, success rate, p95 latency, and active subjects with period-over-period deltas | Must |
| FR-5.2 | Analytics charts volume over time, outcome split, failure reasons, and latency distribution | Must |
| FR-5.3 | Logs are filterable by outcome, key, subject, and date range, and exportable as CSV | Must |
| FR-5.4 | Audit log records every mutating action with actor, target, before/after, IP, and timestamp | Must |
| FR-5.5 | Usage is metered against the plan quota and surfaced at 80% and 100% | Should |

### FR-6 Non-functional

| ID | Requirement |
| --- | --- |
| NFR-1 | p95 verification latency < 800 ms server-side, p99 < 1.5 s (single CPU worker, warm model) |
| NFR-2 | Every list endpoint is paginated, cursor-based, default 20, max 100 |
| NFR-3 | Every tenant-scoped query is filtered by `organization_id` at the repository layer — enforced structurally, not by convention |
| NFR-4 | All errors follow one envelope with a stable `code` |
| NFR-5 | WCAG 2.1 AA: keyboard-navigable, visible focus, 4.5:1 contrast, labelled controls, respects `prefers-reduced-motion` |
| NFR-6 | Lighthouse ≥ 95 on marketing pages; LCP < 2.0 s |
| NFR-7 | Backend test coverage ≥ 70% on services and repositories |
| NFR-8 | Zero PII or biometric data in application logs |

## 7. Pricing & packaging

Usage-based on the unit the customer values: a **verification**. Enrollments are free — charging for onboarding suppresses the very adoption that produces verification volume.

| Plan | Price | Verifications / mo | Subjects | Members | Key limits |
| --- | --- | --- | --- | --- | --- |
| **Free** | $0 | 1,000 | 500 | 2 | 7-day log retention, test + 1 live key |
| **Startup** | $49 / mo | 25,000 | 10,000 | 5 | 30-day retention, webhooks, 5 keys |
| **Growth** | $199 / mo | 150,000 | Unlimited | 20 | 90-day retention, custom threshold, SLA 99.5% |
| **Enterprise** | Custom | Custom | Unlimited | Unlimited | Data residency, on-prem, SSO, 1-year retention, SLA 99.9% |

Overage: $0.004 / verification on Startup, $0.002 on Growth. Free plan hard-stops at quota (`429`), paid plans soft-limit and bill overage — a paid customer's login flow must never be broken by a billing event.

**Trade-off considered:** per-subject (MAU-style) pricing is more predictable for the customer and is what many identity vendors use. It was rejected for MVP because it decouples price from cost — our cost is CPU per inference, which tracks verifications, not stored templates. Aligning price with cost keeps unit economics legible while the product is young.

## 8. Known risks & honest limitations

Stating these plainly is a credibility asset in front of an investor or an examiner, not a weakness.

| Risk | Impact | Mitigation |
| --- | --- | --- |
| **Presentation attacks (printed photo, screen replay, deepfake)** | A face factor without PAD is defeatable. This is the single most important limitation of the MVP. | MVP ships quality gates (moiré/screen-edge heuristics, texture variance, an optional multi-frame active challenge) and **documents that it is not certified PAD**. The `FaceEngine` interface has a `LivenessDetector` slot so a certified model drops in without touching the pipeline. Positioned for step-up auth in-session, not unsupervised remote onboarding. |
| **Demographic bias in the recognition model** | Unequal FRR across skin tone, age, gender is a real and documented property of face recognition. | Threshold calibration is run on a demographically stratified validation set and the per-slice FRR is published in the model card. Per-organization thresholds let customers tune. Documented, not hidden. |
| **Biometric data is irrevocable** | A leaked template is a permanent harm; a leaked password is not. | Store embeddings only, never images by default. Templates are model-specific and not reversible to an image without significant effort, but we treat them as sensitive PII regardless: encrypted disk, strict access control, hard delete on request, no third-party sharing. See [docs/09-security.md](09-security.md). |
| **Regulatory exposure (UU PDP 27/2022, GDPR Art. 9)** | Biometric data is a special category; processing needs explicit consent and a lawful basis. | Consent capture is part of the enrollment API contract (`consent_reference` is required). Data-processing terms, retention controls, and export/delete endpoints ship in MVP. We are the processor; the customer is the controller. |
| **Model licensing** | InsightFace pretrained packs are released for non-commercial research use. | Blocking for revenue, not for the MVP or a portfolio. Documented in [docs/08-ai-workflow.md](08-ai-workflow.md) with the commercial path: license a commercial model or train on a licensed dataset behind the same `FaceEngine` interface — a swap of one adapter, by design. |

## 9. Release criteria

The MVP ships when all of the following are true:

- [ ] A new visitor can register, create an organization, enroll a subject via the console camera, and verify them — with no engineering assistance
- [ ] The same flow is completable purely via the public API using a test key, following only the published docs
- [ ] Every page has designed loading, empty, error, and success states — no raw spinners, no blank screens
- [ ] Threshold calibration is documented with a measured FAR/FRR curve, not a guessed constant
- [ ] The audit log can be exported and demonstrates a full enroll → verify → delete lifecycle
- [ ] `docker compose up` produces a working system from a clean clone on a machine that has never run the project
- [ ] CI is green: lint, type-check, unit, integration, and build for both apps
- [ ] Lighthouse ≥ 95 on `/`, and the console is fully keyboard-navigable

---

**Next:** [02 — Information Architecture](02-information-architecture.md)
